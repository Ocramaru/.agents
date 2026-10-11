"""`.agents/.local/`: notes, standards and config for one machine, read right after their `.agents` and never committed.

Author: Marco Cassar (@Ocramaru)
"""

import uuid
from pathlib import Path

from conftest import git, note, standard

from agentkit import inject, notes, profile, tree


def local(repo: Path, text: str, name: str = "context") -> Path:
  """A note of `name` in `repo/.agents/.local`, with the frontmatter the convention expects."""
  (folder := repo / ".agents" / ".local").mkdir(parents=True, exist_ok=True)
  (folder / f"{name}.md").write_text(f"---\nname: {name}\nkind: {name}\n---\n\n{text}\n")
  return folder / f"{name}.md"


def test_a_local_is_read_right_after_its_agents_and_stamped_like_any_note(repo):
  """Its notes come after its `.agents` under a `./.local/` header, its standards are delivered, and each goes out once a session."""
  folder = local(repo, "LOCAL-RULE only on this machine").parent
  standard(folder / "standards", "mine", applies="*.py", body="LOCAL-STANDARD")
  body, _, sent = tree.payload(repo / "mod.py")
  assert body.index("--- ./context.md ---") < body.index("--- ./.local/context.md ---") and folder / "context.md" in sent
  assert tree.chain(repo / "mod.py") == [repo / ".agents", folder] and tree.find_note_dirs(repo) == [repo / ".agents", folder]
  assert tree.note_dirs_for(folder) == [folder] and notes.is_note(folder / "context.md")

  session = f"local-{uuid.uuid4().hex}"
  text, keys, _ = inject.payload(repo / "mod.py", session)
  inject.mark(session, keys)
  assert "LOCAL-RULE" in text and "LOCAL-STANDARD" in text and "LOCAL-RULE" not in inject.payload(repo / "mod.py", session)[0]


def test_a_local_does_not_demote_its_agents_from_nearest(repo, tmp_path, monkeypatch):
  """A `.local` takes its parent's inject mode, default or set in its agents.toml, so the notes beside it stay `nearest` rather than becoming ancestors."""
  (mine := tmp_path / "profile").mkdir()
  (mine / "config.toml").write_text('[inject]\nnearest = "full"\nancestors = "context"\n')
  monkeypatch.setenv("AGENTS_PROFILE", str(mine))
  monkeypatch.setattr(profile, "LOCAL", tmp_path / "local.toml")   # never this machine's
  note(repo, "# L\n\nNEAR-FINDING", "learned")
  local(repo, "LOCAL-RULE")
  local(repo, "# L\n\nLOCAL-FINDING", "learned")
  body = tree.payload(repo / "mod.py")[0]
  assert "NEAR-FINDING" in body and "LOCAL-FINDING" in body and "--- ./.local/learned.md ---" in body

  note(repo / "pkg", "PKG-RULE")
  (repo / "pkg" / "mod.py").write_text("x\n")
  assert "NEAR-FINDING" not in (deeper := tree.payload(repo / "pkg" / "mod.py")[0]) and "LOCAL-FINDING" not in deeper

  (repo / ".agents" / "agents.toml").write_text('inject = "full"\n')   # set on the parent, it reaches the `.local` too
  assert "LOCAL-FINDING" in tree.payload(repo / "pkg" / "mod.py")[0]


def test_a_local_todo_is_a_note_and_warns_on_a_dropped_task(repo):
  """`.agents/.local/todo.md` is governed like any todo.md: its tasks leave only into its own archive."""
  before = (todo := local(repo, "# TODO\n\n- [ ] Prove the codex backend end to end\n- [ ] Keep this one", "todo")).read_text()
  after = before.replace("- [ ] Prove the codex backend end to end\n", "")
  assert notes.is_note(todo) and notes.is_note(todo.parent / "todo.archive.md") and not notes.is_note(todo.parent / "readme.md")
  assert notes.abandoned(todo, before, after).endswith("  - Prove the codex backend end to end")
  local(repo, "# Done\n\n- [x] Prove the codex backend end to end", "todo.archive")
  assert notes.abandoned(todo, before, after) == ""


def test_a_local_agents_toml_is_the_last_config_layer(repo):
  """Excludes accumulate after the repo's, and any other key set there wins on this machine alone."""
  (repo / ".agents" / "agents.toml").write_text('[review]\nexclude = ["docs/*"]\njobs = 2\n')
  local(repo, "x")
  (repo / ".agents" / ".local" / "agents.toml").write_text('[review]\nexclude = ["scratch/*"]\njobs = 1\n[guard]\nenabled = false\n')
  config = profile.section("review", repo, add=("exclude",))
  assert config["exclude"][-2:] == ["docs/*", "scratch/*"] and config["jobs"] == 1 and profile.section("guard", repo)["enabled"] is False


def test_init_ignores_the_local_notes_and_the_review_ledger_and_tops_up_an_old_ignore(tmp_path):
  """A new `.agents` gets both ignore lines; an old one holding only `.reviews/` keeps its lines and gains `.local/`, once."""
  fresh = git(tmp_path / "fresh")
  assert ".gitignore" in tree.init(fresh)["added"] and (fresh / ".agents" / ".gitignore").read_text() == ".reviews/\n.local/\n"
  old = git(tmp_path / "old")
  (old / ".agents").mkdir()
  (old / ".agents" / ".gitignore").write_text(".reviews/\nmine/\n")
  assert ".gitignore" in tree.init(old)["added"] and (old / ".agents" / ".gitignore").read_text() == ".reviews/\nmine/\n.local/\n"
  assert ".gitignore" not in tree.init(old)["added"] and (old / ".agents" / ".gitignore").read_text() == ".reviews/\nmine/\n.local/\n"
