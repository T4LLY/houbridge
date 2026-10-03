from __future__ import annotations

import sys
from types import SimpleNamespace

import pytest

from houbridge.houdini.scripts.capture.runtime import (
    create_attribute_visualizers,
    destroy_visualizers,
)


class FakeVisualizer:
    def __init__(self, name: str, fail_at: str | None = None) -> None:
        self.name = name
        self.fail_at = fail_at
        self.destroyed = False

    def setLabel(self, _label: str) -> None:
        self._fail("label")

    def setIsActive(self, _active: bool, _viewport) -> None:
        self._fail("activate")

    def destroy(self) -> None:
        self.destroyed = True

    def _fail(self, stage: str) -> None:
        if self.fail_at == stage:
            raise RuntimeError(f"{self.name} {stage} failed")


@pytest.mark.parametrize(
    ("stage", "failed_index"),
    [
        ("label", 0),
        ("setup", 0),
        ("activate", 0),
        ("label", 1),
        ("setup", 1),
        ("activate", 1),
    ],
)
def test_visualizer_setup_failure_destroys_all_created_visualizers(
    monkeypatch: pytest.MonkeyPatch, stage: str, failed_index: int
) -> None:
    created: list[FakeVisualizer] = []
    names = ["first", "second", "third"]

    def create_visualizer(*_args) -> FakeVisualizer:
        index = len(created)
        fail_at = stage if index == failed_index and stage != "setup" else None
        visualizer = FakeVisualizer(names[index], fail_at)
        created.append(visualizer)
        return visualizer

    def setup_visualizer(visualizer, _name, _attribute_class) -> None:
        if visualizer.name == names[failed_index] and stage == "setup":
            raise RuntimeError(f"{visualizer.name} setup failed")

    monkeypatch.setitem(
        sys.modules, "soputils", SimpleNamespace(setupVisualizer=setup_visualizer)
    )
    hou = _fake_hou(create_visualizer)

    with pytest.raises(RuntimeError, match=f"{names[failed_index]} {stage} failed"):
        create_attribute_visualizers(
            object(),
            {"attributes": [{"name": name, "class": "point"} for name in names]},
            hou,
        )

    assert len(created) == failed_index + 1
    assert all(visualizer.destroyed for visualizer in created)


def test_successful_visualizers_remain_caller_owned_until_cleanup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    created: list[FakeVisualizer] = []

    def create_visualizer(*_args) -> FakeVisualizer:
        visualizer = FakeVisualizer(f"visualizer-{len(created)}")
        created.append(visualizer)
        return visualizer

    monkeypatch.setitem(
        sys.modules,
        "soputils",
        SimpleNamespace(setupVisualizer=lambda *_args: None),
    )
    visualizers = create_attribute_visualizers(
        object(),
        {
            "attributes": [
                {"name": "one", "class": "point"},
                {"name": "two", "class": "prim"},
            ]
        },
        _fake_hou(create_visualizer),
    )

    assert visualizers == created
    assert not any(visualizer.destroyed for visualizer in visualizers)
    destroy_visualizers(visualizers)
    assert all(visualizer.destroyed for visualizer in visualizers)


def _fake_hou(create_visualizer):
    category = object()
    return SimpleNamespace(
        viewportVisualizers=SimpleNamespace(
            type=lambda _name: object(),
            setIsCategoryActive=lambda *_args, **_kwargs: None,
            createVisualizer=create_visualizer,
        ),
        viewportVisualizerCategory=SimpleNamespace(Common=category),
    )
