"""Tests for the standards a file gets and the chain of notes it sits in: which are found, in what order, and how a note is mapped and split.

Author: Marco Cassar (@Ocramaru)
"""

import os
from pathlib import Path

import pytest
from conftest import git, note, put

from agentkit import agents as ag, inject, mapblock, notes, profile, review, tree
from agentkit.frontmatter import parse
from agentkit.standards import Library


@pytest.mark.parametrize("files, target, expected", [
  ({"a": "applies: *.py\nrelated: b", "b": "related: c", "c": ""}, "x.py", ["a", "b", "c"]),
  ({"c": "", "b": "extends: c", "a": "applies: *.py\nextends: b"}, "x.py", ["c", "b", "a"]),
  ({"ml": "", "ml.runs": "applies: train_*.py"}, "train_x.py", ["ml", "ml.runs"]),
  ({"ml.runs": "applies: train_*.py"}, "train_x.py", ["ml.runs"]),
  ({"a": "", "a.b": "", "agent": "", "a.b.c": "applies: *.py"}, "x.py", ["a", "a.b", "a.b.c"]),
  ({"agent": "", "agent-notes": "applies: *.md"}, "x.md", ["agent-notes"]),
])
def test_standards_follow_related_namespace_and_extends(tmp_path, files, target, expected):
  for name, header in files.items(): (tmp_path / f"{name}.md").write_text(f"---\nname: {name}\n{header}\n---\n\nbody\n")
  assert [layer.doc.name for layer in Library(tmp_path).for_file(target)] == expected


def test_a_section_naming_a_file_governs_that_file_alone(tmp_path):
  """A filename heading scopes its rules, a prose heading does not, and a split part is governed as its note."""
  (tmp_path / "s.md").write_text("---\nname: s\napplies: *.md\n---\n\n## context.md\n\nCONTEXT-RULE\n\n## learned.md\n\nLEARNED-RULE\n\n## Findings go in learned.md\n\nPROSE-RULE\n\n## All four\n\nSHARED-RULE\n")
  layer = Library(tmp_path).layers["s"][0]

  for name, own, other in (("context.md", "CONTEXT-RULE", "LEARNED-RULE"), ("learned.md", "LEARNED-RULE", "CONTEXT-RULE")):
    rules = layer.for_name(name)
    assert own in rules
    assert other not in rules
    assert "SHARED-RULE" in rules and "PROSE-RULE" in rules

  assert notes.match_name(tmp_path / ".agents" / "learned" / "01-traps.md") == "learned.md"

  document = parse("---\nname: x\nno closing fence\n")     # a hand edit that loses the closing fence loses no text
  assert document.meta == {}
  assert "no closing fence" in document.body


def test_a_repos_agents_toml_reaches_inject_and_review_alike(tmp_path, monkeypatch):
  """[applies] in either TOML shape names a repo's own files, for inject and for review routing."""
  monkeypatch.setattr(profile, "LOCAL", tmp_path / "local.toml")
  assert inject.flatten_applies({"voice": "projects.json"}) == {"voice": ["projects.json"]}
  assert inject.flatten_applies({"ml": {"runs": ["t.py"]}}) == {"ml.runs": ["t.py"]}

  (note(git(tmp_path)) / "agents.toml").write_text('[applies]\nmarkdown = ["go.py", "projects.json"]\n')
  source, prose = put(tmp_path, "go.py", "projects.json")
  assert "markdown" in [layer.doc.name for layer in inject.library_for(source).for_file(source.name)]

  routed = dict(review.plan(["doc-check", "file-review"], ag.definitions(), [prose], [], {}, explicit=False))
  assert routed.get("doc-check") == [prose]
  assert "file-review" not in routed


def test_the_chain_is_outermost_first_stops_at_the_root_and_injects_only_context(tmp_path):
  """Only a .agents holding notes joins the chain, nothing above the repo root does, and only context loads."""
  note(tmp_path / "outside")
  root = git(tmp_path / "outside" / "inner")
  put(root, "standards/x.md", "agents/x.md", "empty/.agents/README.md", "empty/.agents/skills/skill.md")
  agents_directory, deep = note(root, "ROOT-CTX"), root / "src" / "pkg"
  note(deep, "pkg")
  assert tree.is_hub(agents_directory)
  assert tree.chain(deep / "f.py") == tree.find_note_dirs(root) == [agents_directory, deep / ".agents"]

  assert not notes.note_files(root / "empty" / ".agents")     # a README alone opts nothing in
  assert tree.chain(root / "empty" / "f.py") == [agents_directory]
  assert tree.note_dirs_for(root / "empty" / "deep") == tree.note_dirs_for(root / "empty" / ".agents" / "skills") == [agents_directory]

  (agents_directory / "learned.md").write_text("---\nname: learned\nkind: learned\n---\n\n# L\n\n## Traps\n\nx\n")
  body, mention, _ = tree.payload(root / "f.py")
  assert "ROOT-CTX" in body
  assert "Traps" not in body     # only context is injected
  assert any("learned.md" in entry for entry in mention)     # and the rest is advertised

  (agents_directory / "agents.toml").write_text('inject = "none"\n')
  assert tree.payload(root / "f.py")[0] == ""


def test_a_walk_never_enters_a_directory_it_would_skip(tmp_path, monkeypatch):
  """Finding notes and discovering files without git both prune before descending, not after."""
  root = git(tmp_path / "repo")
  note(root)
  note(root / "node_modules" / "pkg")
  skipped = (".venv", "node_modules", "pkg.egg-info", ".ipynb_checkpoints", "cdk.out")
  put(tmp_path / "plain", "src/mod.py", *(f"{name}/noise.py" for name in skipped))

  entered, real_walk = [], os.walk
  def walk(top, *args, **kwargs):
    for current, directories, files in real_walk(top, *args, **kwargs):
      entered.append(Path(current))
      yield current, directories, files
  monkeypatch.setattr(os, "walk", walk)

  assert tree.find_note_dirs(root) == [root / ".agents"]
  assert entered
  assert not [directory for directory in entered if "node_modules" in directory.relative_to(tmp_path).parts]

  entered.clear()
  assert [path.name for path in review.discover(tmp_path / "plain", [], 200_000)] == ["mod.py"]
  assert entered
  assert not [directory for directory in entered if set(skipped) & set(directory.relative_to(tmp_path / "plain").parts)]


def lands(text: str) -> bool:
  """Whether every map row points at the heading it names."""
  rows = [line.strip("|").split("|") for line in text.splitlines() if line.startswith("| ") and " | " in line][1:]
  return bool(rows) and all(text.splitlines()[int(number) - 1].strip().endswith(name.strip()) for name, number in rows)


def test_the_map_settles_in_one_pass_and_split_leaves_the_note_as_an_index(tmp_path):
  """A map numbers the lines it sits in, and a split writes numbered parts with their own map and an index note."""
  applied = mapblock.apply("---\nname: n\n---\n\n# T\n\n## A\n\nx\n\n## B\n\ny\n")
  assert applied.splitlines()[6] == mapblock.START     # below the frontmatter and the title
  assert lands(applied)
  assert mapblock.apply(applied) == applied

  grown = mapblock.apply(applied + "\n## C\n\nz\n")     # a new section resizes the block
  assert lands(grown)
  assert mapblock.apply(grown) == grown
  assert mapblock.START not in mapblock.apply("# T\n\n## Only\n\nx\n")     # one section, no table
  assert [name for name, _ in mapblock.headings("## A\n\n```\n## Not a heading\n```\n\n### B\n".splitlines())] == ["A", "B"]

  path = tmp_path / "learned.md"
  path.write_text(f"---\nname: learned\nkind: learned\n---\n\n# What we learned\n\nNewest first.\n\n{mapblock.START}\n\n| section | line |\n|---|---|\n\n{mapblock.END}\n\n## A\n\n### one\n\nx\n\n### two\n\ny\n\n```md\n## not a section\n```\n\n## B\n\nz\n")
  assert [part.name for part in notes.split(path)] == ["01-a.md", "02-b.md"]
  first = (tmp_path / "learned" / "01-a.md").read_text()
  assert "## not a section" in first
  assert mapblock.START in first     # two subsections, so a map
  assert mapblock.START not in (tmp_path / "learned" / "02-b.md").read_text()

  index = path.read_text()
  assert "(learned/02-b.md)" in index
  assert "## B" not in index
  assert mapblock.START not in index     # the note's own map goes with the sections

  long, bare, headless = put(tmp_path, "long/learned.md", "bare/learned.md", "headless/learned.md", text="## A\n\nx\n\n## B\n\ny\n")
  long.write_text("## Measurement traps, each of which cost a run\n\na\n\n## Open\n\nb\n")
  bare.write_text("# What we learned\n\npreamble\n\n## A\n\nx\n\n## B\n\ny\n")
  assert notes.split(long)[0].name == "01-measurement-traps-each-of-which.md"

  notes.split(bare)
  notes.split(headless)
  assert not bare.read_text().startswith("---")     # no frontmatter is invented
  assert headless.read_text().startswith("Split by section")     # with no preamble the index starts at the first line


def test_split_leaves_alone_a_note_with_nothing_to_split_and_refuses_one_already_split(repo):
  """A note with no sections is untouched, and a second split of a split note raises instead of mixing parts."""
  context = repo / ".agents" / "context.md"
  context.write_text(f"---\nname: context\n---\n\n# r\n\n{mapblock.START}\n\n| section | line |\n|---|---|\n\n{mapblock.END}\n\nno sections here\n")
  before = context.read_bytes()
  assert notes.split(context) == []
  assert context.read_bytes() == before

  context.write_text("---\nname: context\n---\n\n# r\n\n## A\n\na\n\n## B\n\nb\n")
  notes.split(context)
  context.write_text(context.read_text() + "\n## C\n\nc\n")
  with pytest.raises(ValueError, match="already split"): notes.split(context)
  assert sorted(part.name for part in (repo / ".agents" / "context").iterdir()) == ["01-a.md", "02-b.md"]
