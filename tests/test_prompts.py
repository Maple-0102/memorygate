from memorygate.prompts import build_prompt, extract_sql


def test_extract_from_fence():
    assert extract_sql("Here:\n```sql\nSELECT a FROM t;\n```") == "SELECT a FROM t"


def test_extract_takes_last_fence():
    text = "```sql\nSELECT 1\n```\nfixed:\n```sql\nSELECT 2\n```"
    assert extract_sql(text) == "SELECT 2"


def test_extract_unfenced_and_cte():
    assert extract_sql("The answer is SELECT x FROM y;") == "SELECT x FROM y"
    assert extract_sql("```\nWITH a AS (SELECT 1) SELECT * FROM a\n```").startswith("WITH a")


def test_extract_nothing():
    assert extract_sql("") is None
    assert extract_sql("I cannot answer.") is None


def test_prompt_order_and_empty_hints_dropped():
    p = build_prompt("CREATE TABLE t(a);", "Q?", ["", "use a"])
    assert p.index("schema") < p.index("Hints") < p.index("Question")
    assert p.count("- ") == 1
    assert "Hints" not in build_prompt("S", "Q?", [""])
