"""WP4 units: the `next_page` schema (last step only, max_pages 1-10, end required, no stateful, no unknown keys)."""

import pytest

from kfw import form, recipes

RESULT = {"rows": {"pattern": r"\d{2}:\d{2}", "min_rows": 1}}


def flow(np, extra=None, result=None):
    return {"name": "pager", "type": "steps", "description": "fixture", "url": "http://x.test/",
            "steps": [*(extra or []), {"next_page": np}], "result": result or dict(RESULT)}


GOOD = {"click": "下一頁", "max_pages": 3, "end": "disabled"}


def test_valid():
    recipes.validate(flow(GOOD))
    recipes.validate(flow({**GOOD, "max_pages": 1, "end": "absent"}))
    recipes.validate(flow({**GOOD, "max_pages": 10}, extra=[{"click": "查詢", "then": {"text": "x"}}]))


@pytest.mark.parametrize("np,match", [
    ({**GOOD, "max_pages": 0}, "max_pages"),
    ({**GOOD, "max_pages": 11}, "max_pages"),
    ({**GOOD, "max_pages": "3"}, "max_pages"),
    ({**GOOD, "max_pages": True}, "max_pages"),
    ({**GOOD, "max_pages": 2.5}, "max_pages"),
    ({"click": "下一頁", "max_pages": 3}, "end"),
    ({**GOOD, "end": "gone"}, "end"),
    ({**GOOD, "end": None}, "end"),
    ({"max_pages": 3, "end": "absent"}, "click"),
    ({**GOOD, "click": "  "}, "click"),
    ({**GOOD, "stateful": True}, "stateful"),
    ({**GOOD, "then": {"rows": True}}, "unsupported"),
])
def test_bad_next_page(np, match):
    with pytest.raises(recipes.RecipeError, match=match):
        recipes.validate(flow(np))


def test_not_last_step():
    r = flow(GOOD)
    r["steps"].append({"wait": {"text": "x"}})
    with pytest.raises(recipes.RecipeError, match="last step"):
        recipes.validate(r)


def test_step_level_keys_rejected():
    r = flow(GOOD)
    r["steps"][-1]["stateful"] = True
    with pytest.raises(recipes.RecipeError, match="unsupported"):
        recipes.validate(r)
    r = flow(GOOD)
    r["steps"][-1]["then"] = {"rows": True}
    with pytest.raises(recipes.RecipeError, match="unsupported"):
        recipes.validate(r)


def test_needs_result_rows_pattern():
    with pytest.raises(recipes.RecipeError, match="rows.pattern"):
        recipes.validate(flow(GOOD, result={"expect_text": ["x"]}))


def test_find_clickable_is_exported():
    assert callable(form.find_clickable)
