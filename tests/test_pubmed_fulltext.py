"""The PMC full-text haystack must carry the paper's tables.

Publisher JATS puts tables in <floats-group>, OUTSIDE <body>; author
manuscripts put them inline. Grounding can only verify a quote against text
we stored, so a curve that lives in Table 2 is invisible to the appraiser
unless the fetcher flattens every <table-wrap> into the haystack.
"""

from __future__ import annotations

from provenance.sources.pubmed import jats_text

INLINE = """<article>
  <body>
    <sec><p>Higher intake was associated with lower mortality.</p>
    <table-wrap><label>Table 1</label><caption><p>Inline table</p></caption>
      <table><tr><th>Q1</th><th>Q2</th></tr><tr><td>Ref.</td><td>0.95 (0.92, 0.99)</td></tr></table>
    </table-wrap></sec>
  </body>
</article>"""

FLOATED = """<article>
  <body><sec><p>Table 2 shows a nonlinear inverse association.</p></sec></body>
  <floats-group>
    <table-wrap id="T2"><label>Table 2.</label>
      <caption><p>Associations between intake and total mortality.</p></caption>
      <table>
        <thead><tr><th/><th>Q1</th><th>Q2</th><th>Q3</th></tr></thead>
        <tbody>
          <tr><td>Median (IQR), servings/day</td><td>2.1 (1.7-2.5)</td><td>3.3 (3.0-3.5)</td><td>4.2 (4.0-4.5)</td></tr>
          <tr><td>Multivariable-adjusted model</td><td>Ref.</td><td>0.95 (0.92, 0.99)</td><td>0.89 (0.86, 0.92)</td></tr>
        </tbody>
      </table>
      <table-wrap-foot><p>* Adjusted for age.</p></table-wrap-foot>
    </table-wrap>
  </floats-group>
</article>"""


def test_body_prose_is_kept():
    assert "Higher intake was associated with lower mortality." in jats_text(INLINE)


def test_inline_table_is_kept_once():
    text = jats_text(INLINE)
    assert text.count("0.95 (0.92, 0.99)") == 1


def test_floated_table_reaches_the_haystack():
    text = jats_text(FLOATED)
    assert "Table 2." in text
    assert "Associations between intake and total mortality." in text
    # A row reads as one line so a quote can span label and cells.
    assert "Median (IQR), servings/day | 2.1 (1.7-2.5) | 3.3 (3.0-3.5) | 4.2 (4.0-4.5)" in text
    assert "Multivariable-adjusted model | Ref. | 0.95 (0.92, 0.99) | 0.89 (0.86, 0.92)" in text
    assert "* Adjusted for age." in text


def test_no_body_means_no_text():
    assert jats_text("<article><front/></article>") == ""
