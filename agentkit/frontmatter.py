"""Markdown frontmatter. Standards, agent definitions and commands all use it.

Author: Marco Cassar (@Ocramaru)
"""

from pathlib import Path


class Doc:
  """A markdown file's frontmatter and body."""
  def __init__(self, meta: dict[str, str], body: str, path: Path | None = None):
    self.meta, self.body, self.path = meta, body, path

  @property
  def name(self) -> str:
    """The `name` field, else the file's stem."""
    return self.meta.get("name") or (self.path.stem if self.path else "")

  def get(self, key: str, default: str = "") -> str:
    """One frontmatter field, or `default`."""
    return self.meta.get(key, default)

  def list(self, key: str) -> list[str]:
    """A comma-separated field as a list."""
    return [item.strip() for item in self.meta.get(key, "").split(",") if item.strip()]


def parse(text: str, path: Path | None = None) -> Doc:
  """Split `---` frontmatter from the body."""
  lines = text.splitlines()
  if not lines or lines[0].strip() != "---": return Doc({}, text, path)

  meta: dict[str, str] = {}
  for index, line in enumerate(lines[1:], start=2):
    if line.strip() == "---": return Doc(meta, "\n".join(lines[index:]).strip("\n"), path)
    key, separator, value = line.partition(":")
    if separator: meta[key.strip()] = value.strip()

  return Doc({}, text, path)  # unterminated block is a typo; keep the content


def load(path: str | Path) -> Doc:
  """`parse` the file at `path`."""
  path = Path(path)
  return parse(path.read_text(encoding="utf-8"), path)
