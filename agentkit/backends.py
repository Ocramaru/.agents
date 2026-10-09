"""Running a prompt on a CLI or a local HTTP endpoint. Hosts are declared under [backends] in config.toml.

A backend with `resume_argv` keeps its own context between turns; one without gets a replay.

Author: Marco Cassar (@Ocramaru)
"""

import http.client
import json
import re
import subprocess
import time
import urllib.error
import urllib.request
from dataclasses import dataclass

from agentkit import profile as _profile

PLACEHOLDER = re.compile(r"\{(model|prompt|session|effort)\}")


def _fill(template: list[str], values: dict[str, str]) -> list[str]:
  """Fill the placeholders in one pass, so a prompt containing `{model}` is not itself substituted."""
  return [PLACEHOLDER.sub(lambda match: values.get(match.group(1), match.group(0)), argument) for argument in template]


@dataclass
class Reply:
  """A backend's reply, and the session id to resume it."""
  text: str
  session: str | None = None


class Backend:
  """One [backends] entry: a CLI or HTTP endpoint and its models."""
  def __init__(self, name: str, specification: dict):
    self.name, self.spec = name, specification
    self.kind = specification.get("kind", "cli")

  @property
  def resumable(self) -> bool:
    """Whether it resumes a conversation by session id."""
    return bool(self.spec.get("resume_argv"))

  @property
  def parallel(self) -> int:
    """How many requests this backend takes at once: `parallel`, else 1 for http and 4 for a CLI.
    A local http server is one process holding one model, so concurrent calls fail while it swaps."""
    return int(self.spec.get("parallel", 1 if self.kind == "http" else 4))

  @property
  def timeout(self) -> int:
    """Seconds a call may take: `timeout`, else 300."""
    return int(self.spec.get("timeout", 300))

  def release(self, role: str) -> bool:
    """Ask the backend to unload this model, returning True if asked; an unset `release_url` means nothing to release.
    A local server keeps a model loaded for its keep-alive after the last request, whoever else needs the memory."""
    url = self.spec.get("release_url")
    if not url: return False

    request = urllib.request.Request(url, data=json.dumps({"model": self.model_for(role), "keep_alive": 0}).encode(), headers={"Content-Type": "application/json"})
    try:
      with urllib.request.urlopen(request, timeout=30): return True
    except Exception:  # noqa: BLE001 -- a model left loaded is not a failed review
      return False

  def model_for(self, role: str) -> str:
    """The model this backend runs for `role`; raises naming the roles it has when it has none."""
    models = self.spec.get("models", {})
    if role in models: return models[role]
    raise ValueError(f"backend {self.name} has no model for role {role!r}; it has {', '.join(models) or 'none'}. "
                     f"Add one to [backends.{self.name}] models in config.toml, or pick another with --backend")

  def run(self, prompt: str, tier: str = "text", session: str | None = None, effort: str | None = None) -> Reply:
    """Send a prompt to the model for `tier`."""
    model = self.model_for(tier)

    if self.kind == "cli": return self._cli(prompt, model, session, self.timeout, effort)
    if self.kind == "http": return self._http(prompt, model, self.timeout)
    raise ValueError(f"backend {self.name}: unknown kind {self.kind!r}")

  def _cli(self, prompt: str, model: str, session: str | None, timeout: int, effort: str | None = None) -> Reply:
    arguments = _fill(self.spec["resume_argv"] if (session and self.resumable) else self.spec["argv"], {"model": model, "prompt": prompt, "session": session or ""})
    # only when asked for, and only where the backend declares `effort_argv`: an http model has no such flag
    if effort and self.spec.get("effort_argv"): arguments += _fill(self.spec["effort_argv"], {"effort": effort})

    # stdin closed: `claude -p` waits for input on any stdin left open, and a hook's always is
    result = subprocess.run(arguments, capture_output=True, check=False, text=True, timeout=timeout,
                            stdin=subprocess.DEVNULL)
    if result.returncode != 0: raise RuntimeError(f"{self.name} exited {result.returncode}: {result.stderr.strip()[:400]}")
    return self._unwrap(result.stdout.strip(), session)

  def _unwrap(self, out: str, session: str | None) -> Reply:
    """The reply and its session id parsed from the CLI's output, by the backend's `format`."""
    output_format = self.spec.get("format", "text")
    session_key, reply_key = self.spec.get("session_key"), self.spec.get("reply_key")
    if output_format not in ("json", "jsonl"): return Reply(out, session)

    # jsonl: an event stream, the session id early and the reply in a later event; the last of each wins
    if output_format == "jsonl":
      events = [event for line in out.splitlines() if (event := _json(line)) is not None]
      sessions = [found for event in events if (found := _dotted(event, session_key))]
      replies = [str(found) for event in events if (found := _dotted(event, reply_key))]
      return Reply(replies[-1] if replies else out, sessions[-1] if sessions else session)

    # json: one object, possibly between log lines, so the last line that parses is taken first
    parsed = next((found for chunk in [*reversed(out.splitlines()), out[out.find("{"):out.rfind("}") + 1]] if (found := _json(chunk)) is not None), None)
    if parsed is None: return Reply(out, session)
    return Reply(str(_dotted(parsed, reply_key) or out) if reply_key else out, _dotted(parsed, session_key) or session)

  def _http(self, prompt: str, model: str, timeout: int, tries: int = 3) -> Reply:
    """One call, retried with backoff on a transport failure and never on a refusal from the model.
    A local server drops the connection or answers 500 while it swaps weights, which is a wait, not an answer."""
    payload = json.dumps({"model": model, "temperature": 0, "stream": False,
                          "messages": [{"role": "user", "content": prompt}]}).encode()
    last: Exception | None = None

    for attempt in range(tries):
      try:
        with urllib.request.urlopen(urllib.request.Request(self.spec["url"], data=payload, headers={"Content-Type": "application/json"}), timeout=timeout) as response: return Reply(json.loads(response.read())["choices"][0]["message"]["content"].strip())
      except (urllib.error.URLError, http.client.HTTPException, ConnectionError, TimeoutError) as error:
        last = error
        if attempt + 1 < tries: time.sleep(2 * (attempt + 1))

    raise RuntimeError(f"{self.name} unreachable at {self.spec['url']} after {tries} tries: {last}") from last


def _json(chunk: str) -> dict | None:
  chunk = chunk.strip()
  if not chunk.startswith("{"): return None
  try:
    parsed = json.loads(chunk)
  except json.JSONDecodeError: return None
  return parsed if isinstance(parsed, dict) else None


def _dotted(node: dict, path: str | None):
  """Dotted lookup, so a backend's config names `item.text` and the code needs no schema."""
  if not path: return None
  for key in path.split("."):
    if not isinstance(node, dict): return None
    node = node.get(key)
    if node is None: return None
  return node


def load_backends() -> tuple[dict[str, Backend], str]:
  """Every backend by name, a later layer's replacing one of the same name, and the last `default` set."""
  default = (table := _profile.section("backends")).pop("default", "")   # the one plain value among the backends' tables
  backends = {name: Backend(name, specification) for name, specification in table.items()}
  return backends, default or next(iter(backends), "")


def get(name: str | None = None) -> Backend:
  """The named backend, or the default; exits if unknown."""
  backends, default = load_backends()
  chosen = name or default
  if chosen not in backends: raise SystemExit(f"unknown backend {chosen!r}. known: {', '.join(sorted(backends))}")
  return backends[chosen]
