"""A resumable conversation with a subagent, capped by turns. States are A2A's, so `input-required` means it asked.
`send()` takes one new message and the session, not the caller, chooses between a resume and a replay.
The review ledger stores every conversation, so a session holds nothing on disk.

Author: Marco Cassar (@Ocramaru)
"""

import json
import re
import time
from dataclasses import dataclass, field

from agentkit.backends import Backend

STATES = ("working", "input-required", "completed", "failed")
KINDS = ("findings", "question", "proposal", "answer", "decision", "note")
UNREADABLE = "unreadable"   # set by the parser, never by a model: a reply with no reply object in it


@dataclass
class Message:
  """One turn in a conversation."""
  sender: str
  kind: str = "note"
  state: str = "working"
  body: str = ""
  data: dict = field(default_factory=dict)
  at: float = 0.0


class Session:
  """A conversation's messages and its agents' session ids."""
  def __init__(self, task: str, max_turns: int = 8):
    self.task, self.max_turns = task, max_turns
    self.messages: list[Message] = []
    self.handles: dict[str, str] = {}  # agent name -> backend session id

  def transcript(self) -> str:
    """Every message as a transcript entry: who, what kind, what state, then the body and any data."""
    return "\n\n".join(f"[{message.sender} · {message.kind} · {message.state}]\n{message.body}"
                       + (f"\n{json.dumps(message.data, indent=2)}" if message.data else "")
                       for message in self.messages)

  def post(self, message: Message) -> Message:
    """Append a message, stamping its time."""
    message.at = message.at or time.time()
    self.messages.append(message)
    return message

  def send(self, agent: str, backend: Backend, body: str, instructions: str = "",
           tier: str = "text", kind: str = "note", effort: str | None = None) -> Message:
    """One turn. `instructions` go only on the opening turn, or the prompt drifts."""
    # checked before posting, or the last message counts against the cap and is never sent
    if len(self.messages) + 1 >= self.max_turns:
      return self.post(Message(agent, "note", "failed", f"turn cap of {self.max_turns} reached"))
    self.post(Message("caller", kind, "working", body))

    handle = self.handles.get(agent)
    opening = handle is None or not backend.resumable

    parts = []
    if opening and instructions: parts.append(instructions)
    if opening and len(self.messages) > 1: parts.append(f"The conversation so far:\n\n{self.transcript()}")
    else: parts.append(body)
    parts.append(PROTOCOL)

    try:
      reply = backend.run("\n\n".join(parts), tier=tier, session=handle, effort=effort)
    except Exception as error:  # noqa: BLE001
      # no reply, no turn: recording one spends the cap on network noise and replays it to the model
      self.messages.pop()
      return Message(agent, "note", "failed", f"{type(error).__name__}: {error}", at=time.time())

    if reply.session: self.handles[agent] = reply.session
    return self.post(_parse(reply.text, agent))

  def answer(self, agent: str, backend: Backend, body: str, tier: str, effort: str | None = None) -> Message:
    """Continue a conversation. `tier` has no default: a reply on another model is another reviewer."""
    return self.send(agent, backend, body, tier=tier, kind="answer", effort=effort)


PROTOCOL = f"""Reply with one JSON object and nothing else:

{{"kind": "<{'|'.join(KINDS)}>", "state": "<{'|'.join(STATES)}>", "body": "...", "data": {{}}}}

`data` carries the structured result your instructions asked for, and `body` is one line about it.
Anything you report only in `body` is read by a human and by nothing else, so a finding that belongs
in `data` and is written as prose instead is a finding you did not report.

Use `state: input-required` with `kind: question` only when you need something you were not given.
Every value is valid JSON: a line range is a string, "99-106", never a bare 99-106.
Use `kind: proposal` to offer a fix and let the caller decide who applies it. Use `state: completed`
when there is nothing left to say, including when you found nothing wrong."""


def _parse(raw: str, sender: str) -> Message:
  """The reply object, wherever it sits in the prose and fences a model wraps it in.
  An unreadable reply is `failed`, not `completed`: it is not a review that found nothing."""
  text = raw.strip()
  parsed = _reply_object(text) or _reply_object(BARE_RANGE.sub(r'\1"\2"', text))
  if parsed is None: return Message(sender, UNREADABLE, "failed", text)   # the kind says why, for the report

  kind, state = parsed.get("kind", "note"), parsed.get("state", "working")
  data = parsed.get("data")
  # a bare list is the findings themselves, which models return about as often as the mapping
  data = {"findings": data} if isinstance(data, list) else data if isinstance(data, dict) else {}
  return Message(sender, kind if kind in KINDS else "note", state if state in STATES else "working",
                 str(parsed.get("body", "")), data)


# a line range written bare, `"line": 99-106`, is the malformation reviews produce
BARE_RANGE = re.compile(r'("line"\s*:\s*)(\d+\s*-\s*\d+)')


def _reply_object(text: str) -> dict | None:
  """The first object that decodes and has a `kind`, `state` or `data` key.
  `raw_decode` stops at the object's own close, so a brace or another object after it does not end it early or late."""
  decode, at = json.JSONDecoder().raw_decode, text.find("{")

  while at != -1:
    try:
      parsed, _ = decode(text, at)
      if isinstance(parsed, dict) and parsed.keys() & {"kind", "state", "data"}: return parsed
    except json.JSONDecodeError: pass
    at = text.find("{", at + 1)
  return None