import json
from pathlib import Path


def read_category_content(directory):
    return json.loads((directory.parent / "categories.json").read_text(encoding="utf-8"))


def build_preai(directory):
    categories = read_category_content(directory)
    selections = directory / "user_liked_categories"
    sections = []
    for name in selections.read_text(encoding="utf-8").splitlines():
        if not name:
            continue
        if name not in categories:
            raise ValueError(f"Selected category {name!r} is missing from categories.json")
        sections.append(f"---{name}---\n{categories[name]}\n")
    target = directory / "preAI.md"
    temp = target.with_suffix(".md.tmp")
    temp.write_text("".join(sections), encoding="utf-8")
    temp.replace(target)


if __name__ == "__main__":
    build_preai(Path(__file__).resolve().parent / "user_data")
