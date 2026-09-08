"""Quick standalone sanity check for indexer/chunker.py — no Qdrant/network
needed. Run with:

    python scripts/test_chunker.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from indexer.chunker import chunk_source

PY_SAMPLE = '''
import os


def helper(x):
    return x + 1


class Widget:
    def __init__(self, name):
        self.name = name

    def render(self):
        return f"<div>{self.name}</div>"


@dataclass
class Config:
    debug: bool = False
'''

TSX_SAMPLE = '''
import React from "react";

export function Header({ title }) {
  return <h1>{title}</h1>;
}

const SubmitButton = ({ onClick }) => {
  return <button className="bg-blue-600" onClick={onClick}>Submit</button>;
};

export default function AssessmentPage() {
  return (
    <div>
      <Header title="Assessment" />
      <SubmitButton onClick={() => {}} />
    </div>
  );
}

class Legacy extends React.Component {
  handleClick() {
    console.log("clicked");
  }

  render() {
    return <div />;
  }
}
'''


def describe(chunks):
    for c in chunks:
        print(f"  [{c.chunk_type:9}] {c.symbol_name:20} lines {c.start_line}-{c.end_line}  is_page={c.is_page}")


def main():
    print("=== Python (utils/helpers.py) ===")
    py_chunks = chunk_source(PY_SAMPLE, "python", "utils/helpers.py")
    describe(py_chunks)
    assert {c.symbol_name for c in py_chunks} == {"helper", "Widget", "Widget.__init__", "Widget.render", "Config"}
    assert next(c for c in py_chunks if c.symbol_name == "Widget").chunk_type == "class"
    assert next(c for c in py_chunks if c.symbol_name == "Widget.render").chunk_type == "method"

    print("\n=== TSX (pages/Assessment.tsx) ===")
    tsx_chunks = chunk_source(TSX_SAMPLE, "tsx", "pages/Assessment.tsx", is_page=True)
    describe(tsx_chunks)
    names = {c.symbol_name for c in tsx_chunks}
    assert {"Header", "SubmitButton", "AssessmentPage", "Legacy", "Legacy.handleClick", "Legacy.render"} <= names
    assert next(c for c in tsx_chunks if c.symbol_name == "SubmitButton").chunk_type == "component"
    assert next(c for c in tsx_chunks if c.symbol_name == "AssessmentPage").chunk_type == "component"
    assert all(c.is_page for c in tsx_chunks)

    print("\nAll assertions passed.")


if __name__ == "__main__":
    main()
