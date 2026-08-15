from io import BytesIO
from zipfile import ZIP_DEFLATED, ZipFile

import pytest
from datetime import date

from lesson_agent.weekly_plan import PlanParseError, _extract_hwpx, parse_lessons


def _hwpx_bytes(section_xml: str) -> bytes:
    buffer = BytesIO()
    with ZipFile(buffer, "w", ZIP_DEFLATED) as archive:
        archive.writestr("Contents/section0.xml", section_xml)
    return buffer.getvalue()


MINIMAL_TABLE = """
<hp:section xmlns:hp="http://www.hancom.co.kr/hwpml/2011/paragraph">
  <hp:tbl>
    <hp:tr>
      <hp:tc><hp:subList><hp:p><hp:run><hp:t>요일</hp:t></hp:run></hp:p></hp:subList></hp:tc>
      <hp:tc><hp:subList><hp:p><hp:run><hp:t>월</hp:t></hp:run></hp:p></hp:subList></hp:tc>
      <hp:tc><hp:subList><hp:p><hp:run><hp:t>화</hp:t></hp:run></hp:p></hp:subList></hp:tc>
    </hp:tr>
    <hp:tr>
      <hp:tc><hp:subList><hp:p><hp:run><hp:t>1교시</hp:t></hp:run></hp:p></hp:subList></hp:tc>
      <hp:tc><hp:subList><hp:p><hp:run><hp:t>국어</hp:t></hp:run></hp:p></hp:subList></hp:tc>
      <hp:tc><hp:subList><hp:p><hp:run><hp:t>수학</hp:t></hp:run></hp:p></hp:subList></hp:tc>
    </hp:tr>
  </hp:tbl>
</hp:section>
""".strip()


def test_hwpx_table_keeps_row_and_column_order(tmp_path):
    path = tmp_path / "minimal.hwpx"
    path.write_bytes(_hwpx_bytes(MINIMAL_TABLE))

    text = _extract_hwpx(path)

    assert "TABLE | 0 | 0 | 요일" in text
    assert "TABLE | 1 | 1 | 국어" in text
    assert text.index("TABLE | 1 | 1 | 국어") < text.index("TABLE | 1 | 2 | 수학")


def test_hwpx_empty_document_is_unreadable(tmp_path):
    path = tmp_path / "empty.hwpx"
    path.write_bytes(_hwpx_bytes("<hp:section xmlns:hp='http://www.hancom.co.kr/hwpml/2011/paragraph'/>"))

    with pytest.raises(PlanParseError, match="표"):
        _extract_hwpx(path)


def test_hwpx_plan_tables_are_resolved_to_lessons(tmp_path):
    def table(rows: list[list[str]]) -> str:
        row_xml = []
        for row in rows:
            cells = "".join(
                f"<hp:tc><hp:subList><hp:p><hp:run><hp:t>{cell}</hp:t></hp:run></hp:p></hp:subList></hp:tc>"
                for cell in row
            )
            row_xml.append(f"<hp:tr>{cells}</hp:tr>")
        return f"<hp:tbl>{''.join(row_xml)}</hp:tbl>"

    section = f"""
    <hp:section xmlns:hp="http://www.hancom.co.kr/hwpml/2011/paragraph">
      {table([
          ["과목", "단원명", "학습내용", "쪽수", "차시"],
          ["과학", "기체의 성질", "기체의 부피를 관찰해요", "10-11", "1/1"],
      ])}
      {table([
          ["2반", "월", "화", "수", "목", "금"],
          ["1", "국", "수", "국", "과", "국"],
      ])}
    </hp:section>
    """
    path = tmp_path / "plan.hwpx"
    path.write_bytes(_hwpx_bytes(section))

    lessons = parse_lessons(_extract_hwpx(path), target_date=date(2026, 8, 20), class_number=2)

    assert lessons[0].subject == "과학"
    assert lessons[0].topic == "기체의 부피를 관찰해요"
