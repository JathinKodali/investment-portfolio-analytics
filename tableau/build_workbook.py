"""
build_workbook.py
-----------------
Builds the packaged Tableau workbook

    tableau/Investment_Portfolio_Analytics.twbx

from the CSV files that main.py writes to data/tableau/.

How to run (after main.py):
    python tableau/build_workbook.py

WHAT: A .twbx file is a zip that holds a workbook (.twb, which is XML) plus
      the data files. This script writes that XML and zips it with the CSVs.
WHY:  The workbook always matches the latest pipeline output, and every chart
      setting (fields, colours, formats, layout) is written down in one place.

NOTE: Re-running this script overwrites the workbook. If you edit the workbook
      by hand in Tableau, save it under a different name first.

Workbook contents
  Dashboards : Market Overview (Phases 1-2), Portfolio Performance (3, 5, 6),
               Risk & Return (4, 13), Goal Simulator (7-12)
  Worksheets : one per chart, plus small hidden KPI text sheets used only on
               the dashboards
  Parameters : the five Goal Simulator inputs
"""

import csv
import hashlib
import re
import uuid
import zipfile
from pathlib import Path
from xml.sax.saxutils import escape

PROJECT_ROOT = Path(__file__).resolve().parent.parent
TABLEAU_DATA_DIR = PROJECT_ROOT / "data" / "tableau"
OUTPUT_FILE = PROJECT_ROOT / "tableau" / "Investment_Portfolio_Analytics.twbx"
TWB_NAME = "Investment_Portfolio_Analytics.twb"

MARKET_CSV = "tableau_market_data.csv"
ALLOCATION_CSV = "tableau_portfolio_allocation.csv"

# Design size in pixels. Dashboards use Automatic sizing, so Tableau
# stretches this 1366 x 768 layout to fill the window (or the screen in
# Presentation Mode); positions are stored as fractions of the size.
DASH_W, DASH_H = 1366, 768

STOCK_PARAM_REF = "[Parameters].[Parameter 6]"
ALL_STOCKS = "All stocks"

# ---------------------------------------------------------------------------
# Colours
# ---------------------------------------------------------------------------
# One colour per stock, assigned in a fixed order (alphabetical tickers) so a
# stock keeps the same colour on every chart, even when others are filtered
# out. This 6-colour order passed a colour-blind safety check (adjacent
# colours stay distinguishable for the common types of colour blindness).
SERIES_COLOURS = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300",
                  "#4a3aa7", "#e34948"]

INK = "#1b1b1a"          # main text
INK_2 = "#52514e"        # secondary text
INK_3 = "#898781"        # muted labels
GAIN = "#006300"         # positive return text
LOSS = "#b3261e"         # negative return text
PAGE_BG = "#f2f2ef"      # dashboard background
CARD_BG = "#ffffff"      # chart card background
CARD_BORDER = "#dcdbd4"  # hairline card border
HEADER_BG = "#17212f"    # title band
HEADER_SUB = "#c3c8d2"   # subtitle text on the title band
WIRE = "#9aa3b0"         # dashed outline for concept wireframes


# ---------------------------------------------------------------------------
# Small XML helpers
# ---------------------------------------------------------------------------
def a(value):
    """Escape a value for use inside a single-quoted XML attribute."""
    return escape(str(value), {"'": "&apos;", '"': "&quot;"})


def stable_id(seed, length=28):
    """A repeatable random-looking id (Tableau uses these for data sources)."""
    digest = hashlib.sha1(seed.encode()).hexdigest()
    alphabet = "0123456789abcdefghijklmnopqrstuvwxyz"
    number = int(digest, 16)
    out = ""
    while len(out) < length:
        number, rem = divmod(number, 36)
        out += alphabet[rem]
    return out


def stable_uuid(seed):
    return "{" + str(uuid.UUID(hashlib.md5(seed.encode()).hexdigest())).upper() + "}"


def calc_name(caption):
    """Tableau-style internal name for a calculated field."""
    return "Calculation_" + str(int(hashlib.md5(caption.encode()).hexdigest(), 16))[:19]


# ---------------------------------------------------------------------------
# Data source model
# ---------------------------------------------------------------------------
class Column:
    """One field in a data source: a CSV column or a calculated field."""

    def __init__(self, name, datatype, caption=None, fmt=None, agg=None,
                 formula=None, role=None, ctype=None):
        self.name = name                # internal name, e.g. Close
        self.datatype = datatype        # string | date | real | integer
        self.caption = caption          # display name in Tableau
        self.fmt = fmt                  # Tableau number format code
        self.formula = formula          # set for calculated fields
        if role is None:
            role = "dimension" if datatype in ("string", "date") else "measure"
        if ctype is None:
            ctype = {"string": "nominal", "date": "ordinal"}.get(datatype, "quantitative")
        self.role, self.ctype = role, ctype
        self.agg = agg or {"string": "Count", "date": "Year"}.get(datatype, "Sum")

    def definition_xml(self, indent):
        attrs = []
        if self.caption:
            attrs.append(f"caption='{a(self.caption)}'")
        attrs.append(f"datatype='{self.datatype}'")
        if self.fmt:
            attrs.append(f"default-format='{a(self.fmt)}'")
        attrs += [f"name='[{a(self.name)}]'", f"role='{self.role}'", f"type='{self.ctype}'"]
        open_tag = f"{indent}<column {' '.join(attrs)}"
        if self.formula is None:
            return open_tag + " />"
        return (f"{open_tag}>\n{indent}  <calculation class='tableau' formula='{a(self.formula)}' />\n"
                f"{indent}</column>")


class DataSource:
    def __init__(self, caption, filename, columns, calcs=(), palette_field=None, palette=None):
        self.caption = caption
        self.filename = filename
        self.columns = columns
        self.calcs = list(calcs)
        self.name = "federated." + stable_id("ds:" + filename)
        self.conn = "textscan." + stable_id("conn:" + filename)
        self.object_id = filename + "_" + hashlib.md5(filename.encode()).hexdigest().upper()
        self.palette_field = palette_field  # e.g. "Ticker"
        self.palette = palette or {}        # {"AAPL": "#2a78d6", ...}
        self.by_name = {c.name: c for c in columns + self.calcs}

    def col(self, name):
        return self.by_name[name]


class Field:
    """A field as used on a shelf (Tableau calls this a column-instance)."""

    PREFIX = {"None": "none", "Sum": "sum", "Avg": "avg", "User": "usr",
              "Attribute": "attr", "Min": "min", "Max": "max"}

    def __init__(self, ds, column_name, derivation="None", table_calc_by=None):
        self.ds = ds
        self.column = ds.col(column_name)
        self.derivation = derivation
        self.table_calc_by = table_calc_by  # a Field to compute a table calc along
        if derivation == "None" and self.column.datatype == "date":
            self.itype = "quantitative"     # continuous date axis
        elif derivation in ("None", "Attribute") and self.column.datatype == "string":
            self.itype = "nominal"
        elif derivation == "User" and self.column.datatype == "string":
            self.itype = "nominal"
        else:
            self.itype = "quantitative"

    @property
    def local(self):
        suffix = {"quantitative": "qk", "nominal": "nk", "ordinal": "ok"}[self.itype]
        return f"[{self.PREFIX[self.derivation]}:{self.column.name}:{suffix}]"

    @property
    def ref(self):
        return f"[{self.ds.name}].{self.local}"

    def instance_xml(self, indent):
        head = (f"{indent}<column-instance column='[{a(self.column.name)}]' derivation='{self.derivation}' "
                f"name='{a(self.local)}' pivot='key' type='{self.itype}'")
        if self.table_calc_by is None:
            return head + " />"
        return (f"{head}>\n{indent}  <table-calc ordering-field='{a(self.table_calc_by.ref)}' "
                f"ordering-type='Field' />\n{indent}</column-instance>")


def field_tag(field):
    """Text that inserts a field's value into a label or tooltip."""
    return f"<![CDATA[<{field.ref}>]]>"


# ---------------------------------------------------------------------------
# Formatted text (titles, labels, tooltips, text boxes)
# ---------------------------------------------------------------------------
def run(text, size=None, color=None, bold=False, font=None, align=None, raw=False):
    """One piece of formatted text. raw=True means text is already XML."""
    attrs = []
    if bold:
        attrs.append("bold='true'")
    if align is not None:
        attrs.append(f"fontalignment='{align}'")
    if color:
        attrs.append(f"fontcolor='{color}'")
    if font:
        attrs.append(f"fontname='{a(font)}'")
    if size:
        attrs.append(f"fontsize='{size}'")
    body = text if raw else escape(text)
    return f"<run{(' ' + ' '.join(attrs)) if attrs else ''}>{body}</run>"


NEWLINE = "<run>Æ&#10;</run>"


def formatted_text(runs, indent):
    inner = "\n".join(f"{indent}  {r}" for r in runs)
    return f"{indent}<formatted-text>\n{inner}\n{indent}</formatted-text>"


# ---------------------------------------------------------------------------
# Read the CSV files (to get the date range for the date filter)
# ---------------------------------------------------------------------------
def read_csv_rows(filename):
    path = TABLEAU_DATA_DIR / filename
    if not path.exists():
        raise FileNotFoundError(f"{path} not found. Run 'python main.py' first.")
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


# ---------------------------------------------------------------------------
# Data source definitions
# ---------------------------------------------------------------------------
USD = 'c"$"#,##0.00;-"$"#,##0.00'
USD0 = 'c"$"#,##0;-"$"#,##0'
PCT_SIGNED = "*+0.0%;-0.0%;0.0%"
COUNT = "n#,##0;-#,##0"


def build_market_source(tickers):
    columns = [
        Column("Date", "date"),
        Column("Ticker", "string"),
        Column("Company", "string"),
        Column("Sector", "string"),
        Column("Open", "real", fmt=USD, agg="Avg"),
        Column("High", "real", fmt=USD, agg="Avg"),
        Column("Low", "real", fmt=USD, agg="Avg"),
        Column("Close", "real", fmt=USD, agg="Avg"),
        Column("Adjusted_Close", "real", "Adjusted Close", fmt=USD, agg="Avg"),
        Column("Volume", "integer", fmt=COUNT, agg="Sum"),
        Column("Daily_Return", "real", "Daily Return", fmt="p0.00%", agg="Avg"),
        Column("Cumulative_Return", "real", "Cumulative Return", fmt="p0.0%", agg="Avg"),
        Column("Price_Change", "real", "Price Change", fmt=USD, agg="Sum"),
        Column("Price_Change_Percentage", "real", "Price Change (%)",
               fmt='n#,##0.00"%";-#,##0.00"%"', agg="Avg"),
    ]
    period = Column(
        calc_name("Cumulative Return % (Selected Period)"), "real",
        "Cumulative Return % (Selected Period)", fmt=PCT_SIGNED,
        # Compounds the daily returns of the rows left after filtering:
        # product(1 + r) - 1, written as EXP(SUM(LN(1 + r))) - 1 because
        # Tableau has no PRODUCT() function. It follows the Date filter.
        formula="EXP(SUM(LN(1 + [Daily_Return]))) - 1")
    calcs = [
        period,
        Column(calc_name("Stocks Tracked"), "integer", "Stocks Tracked", fmt=COUNT,
               formula="COUNTD([Ticker])"),
        Column(calc_name("Sectors Covered"), "integer", "Sectors Covered", fmt=COUNT,
               formula="COUNTD([Sector])"),
        Column(calc_name("Trading Days"), "integer", "Trading Days", fmt=COUNT,
               formula="COUNTD([Date])"),
        Column(calc_name("Date Range Label"), "string", "Date Range Label",
               role="measure", ctype="nominal",
               formula=("STR(DAY(MIN([Date]))) + ' ' + LEFT(DATENAME('month', MIN([Date])), 3) + ' ' + "
                        "STR(YEAR(MIN([Date]))) + ' – ' + STR(DAY(MAX([Date]))) + ' ' + "
                        "LEFT(DATENAME('month', MAX([Date])), 3) + ' ' + STR(YEAR(MAX([Date])))")),
        Column(calc_name("Return Rank (Best First)"), "integer", "Return Rank (Best First)",
               formula=f"RANK([{period.name}], 'desc')"),
        Column(calc_name("Return Rank (Worst First)"), "integer", "Return Rank (Worst First)",
               formula=f"RANK([{period.name}], 'asc')"),
    ]
    # Company selection is driven by the "Stock" parameter (a drop-down), not
    # by a shared quick filter: Tableau 2026.3 re-saves a shared categorical
    # quick filter without its data-source name and then cannot reopen it
    # ("Field ... which is included for filtering does not exist").
    # Appended last so the positions above stay the same.
    calcs.append(Column(calc_name("In Stock Selection"), "string", "In Stock Selection",
                        formula=(f"IIF({STOCK_PARAM_REF} = '{ALL_STOCKS}' OR [Company] = "
                                 f"{STOCK_PARAM_REF}, 'Yes', 'No')"),
                        role="dimension", ctype="nominal"))
    palette = {t: SERIES_COLOURS[i % len(SERIES_COLOURS)] for i, t in enumerate(tickers)}
    return DataSource("Market Data", MARKET_CSV, columns, calcs, "Ticker", palette)


def build_allocation_source(tickers):
    columns = [
        Column("Ticker", "string"),
        Column("Company", "string"),
        Column("Sector", "string"),
        Column("Quantity", "integer", fmt=COUNT, agg="Sum"),
        Column("Purchase_Price", "real", "Purchase Price", fmt=USD, agg="Avg"),
        Column("Purchase_Date", "date", "Purchase Date"),
        Column("Investment_Amount", "real", "Investment Amount", fmt=USD0, agg="Sum"),
        Column("Data_Label", "string", "Data Label"),
    ]
    calcs = [
        # Share of the total amount invested. The FIXED expression is the
        # total across all holdings, so each tile's share adds up to 100%.
        Column(calc_name("Share of Amount Invested"), "real", "Share of Amount Invested",
               fmt="p0.0%",
               formula="SUM([Investment_Amount]) / MIN({FIXED : SUM([Investment_Amount])})"),
        Column(calc_name("Number of Holdings"), "integer", "Number of Holdings", fmt=COUNT,
               formula="COUNTD([Ticker])"),
    ]
    palette = {t: SERIES_COLOURS[i % len(SERIES_COLOURS)] for i, t in enumerate(tickers)}
    return DataSource("Portfolio Allocation (Sample)", ALLOCATION_CSV, columns, calcs,
                      "Ticker", palette)


REMOTE_TYPE = {"string": 129, "date": 133, "real": 5, "integer": 20}

# Tableau Public only accepts workbooks whose data sources are extracts, so by
# default every data source connects to a Tableau extract (.hyper) written from
# its CSV and packaged inside the .twbx (same layout as Tableau's own sample
# workbooks). "python tableau/build_workbook.py --live" connects to the CSVs.
USE_EXTRACTS = True


def extract_name(csv_name):
    return csv_name.replace(".csv", ".hyper")


def datasource_xml(ds):
    base = ds.columns
    table = ds.filename.replace(".csv", "#csv")
    rel_cols = "\n".join(
        f"                  <column datatype='{c.datatype}' name='{a(c.name)}' ordinal='{i}' />"
        for i, c in enumerate(base))
    rel_cols_conn = rel_cols.replace("                  ", "            ")

    hyper_conn = "hyper." + stable_id("hyper:" + ds.filename)
    if USE_EXTRACTS:
        parent = "Extract"
        relation = (f"<relation connection='{hyper_conn}' name='Extract' "
                    "table='[Extract].[Extract]' type='table' />")
        connection = (
            f"        <named-connections>\n"
            f"          <named-connection caption='{a(ds.caption)}' name='{hyper_conn}'>\n"
            f"            <connection authentication='auth-none' author-locale='en_US' class='hyper' "
            f"dbname='Data/Extracts/{a(extract_name(ds.filename))}' default-settings='yes' port='' "
            f"sslmode='' username='tableau_internal_user' />\n"
            f"          </named-connection>\n        </named-connections>\n"
            f"        {relation}\n")
        capability = ""
        object_relation = f"              {relation}\n"
    else:
        parent = ds.filename
        connection = None   # filled in below (text file connection)
    records = []
    for i, c in enumerate(base):
        extra = ""
        if c.datatype == "string":
            extra = ("            <scale>1</scale>\n            <width>1073741823</width>\n")
        collation = ("            <collation flag='0' name='LEN_RUS' />\n"
                     if c.datatype == "string" else "")
        records.append(
            "          <metadata-record class='column'>\n"
            f"            <remote-name>{escape(c.name)}</remote-name>\n"
            f"            <remote-type>{REMOTE_TYPE[c.datatype]}</remote-type>\n"
            f"            <local-name>[{escape(c.name)}]</local-name>\n"
            f"            <parent-name>[{escape(parent)}]</parent-name>\n"
            f"            <remote-alias>{escape(c.name)}</remote-alias>\n"
            f"            <ordinal>{i}</ordinal>\n"
            f"            <local-type>{c.datatype}</local-type>\n"
            f"            <aggregation>{c.agg}</aggregation>\n"
            f"{extra}"
            "            <contains-null>true</contains-null>\n"
            f"{collation}"
            f"            <object-id>[{escape(ds.object_id)}]</object-id>\n"
            "          </metadata-record>")

    column_defs = "\n".join(c.definition_xml("      ") for c in base + ds.calcs
                            if c.caption or c.fmt or c.formula is not None)

    palette = ""
    palette_instance = ""
    if ds.palette:
        # Tableau only applies a saved colour palette when the coloured field
        # is also declared at data-source level.
        palette_instance = Field(ds, ds.palette_field).instance_xml("      ") + "\n"
        maps = "\n".join(
            f"            <map to='{colour}'>\n"
            f"              <bucket>&quot;{a(value)}&quot;</bucket>\n"
            "            </map>" for value, colour in ds.palette.items())
        palette = (
            "      <style>\n        <style-rule element='mark'>\n"
            f"          <encoding attr='color' field='[none:{ds.palette_field}:nk]' type='palette'>\n"
            f"{maps}\n          </encoding>\n        </style-rule>\n      </style>\n")

    if connection is None:
        connection = (
            f"        <named-connections>\n"
            f"          <named-connection caption='{a(ds.filename.replace('.csv', ''))}' name='{ds.conn}'>\n"
            f"            <connection class='textscan' directory='Data/tableau' filename='{a(ds.filename)}' password='' server='' />\n"
            f"          </named-connection>\n        </named-connections>\n"
            f"        <relation connection='{ds.conn}' name='{a(ds.filename)}' table='[{a(table)}]' type='table'>\n"
            f"          <columns character-set='UTF-8' header='yes' locale='en_US' separator=','>\n"
            f"{rel_cols_conn}\n          </columns>\n        </relation>\n")
        capability = f"""          <metadata-record class='capability'>
            <remote-name />
            <remote-type>0</remote-type>
            <parent-name>[{escape(ds.filename)}]</parent-name>
            <remote-alias />
            <aggregation>Count</aggregation>
            <contains-null>true</contains-null>
            <attributes>
              <attribute datatype='string' name='character-set'>&quot;UTF-8&quot;</attribute>
              <attribute datatype='string' name='collation'>&quot;en_US&quot;</attribute>
              <attribute datatype='string' name='currency'>&quot;$&quot;</attribute>
              <attribute datatype='string' name='field-delimiter'>&quot;,&quot;</attribute>
              <attribute datatype='string' name='header-row'>&quot;true&quot;</attribute>
              <attribute datatype='string' name='locale'>&quot;en_US&quot;</attribute>
              <attribute datatype='string' name='single-char'>&quot;&quot;</attribute>
            </attributes>
          </metadata-record>
"""
        object_relation = (
            f"              <relation connection='{ds.conn}' name='{a(ds.filename)}' table='[{a(table)}]' type='table'>\n"
            f"                <columns character-set='UTF-8' header='yes' locale='en_US' separator=','>\n"
            f"{rel_cols}\n                </columns>\n              </relation>\n")

    return f"""    <datasource caption='{a(ds.caption)}' inline='true' name='{ds.name}' version='18.1'>
      <connection class='federated'>
{connection}        <metadata-records>
{capability}{chr(10).join(records)}
        </metadata-records>
      </connection>
      <aliases enabled='yes' />
{column_defs}
{palette_instance}      <layout dim-ordering='alphabetic' measure-ordering='alphabetic' show-structure='true' />
{palette}      <semantic-values>
        <semantic-value key='[Country].[Name]' value='&quot;United States&quot;' />
      </semantic-values>
      <object-graph>
        <objects>
          <object caption='{a(ds.filename)}' id='{a(ds.object_id)}'>
            <properties context=''>
{object_relation}            </properties>
          </object>
        </objects>
      </object-graph>
    </datasource>"""


# ---------------------------------------------------------------------------
# Worksheets
# ---------------------------------------------------------------------------
class Sheet:
    """Everything needed to write one worksheet."""

    def __init__(self, name, ds, mark, title_runs=None, rows=None, cols=None,
                 encodings=(), tooltip_runs=None, label_runs=None, filters=(),
                 sort=None, table_style="", mark_style="", pane_style="", hidden=False,
                 label_show=True, uses_params=False):
        self.name, self.ds, self.mark = name, ds, mark
        self.title_runs = title_runs
        self.rows, self.cols = rows, cols
        self.encodings = list(encodings)     # [(attr, Field)]
        self.tooltip_runs = tooltip_runs
        self.label_runs = label_runs
        self.filters = list(filters)         # [(xml, Field, is_slice)]
        self.sort = sort                     # (Field dim, Field measure, 'DESC')
        self.table_style = table_style
        self.mark_style = mark_style
        self.pane_style = pane_style
        self.hidden = hidden
        self.label_show = label_show
        self.uses_params = uses_params      # True when a calc reads a parameter

    def fields(self):
        out = [f for _, f in self.encodings]
        out += [f for f in (self.rows, self.cols) if f is not None]
        out += [f for _, f, _ in self.filters]
        if self.sort:
            out += [self.sort[0], self.sort[1]]
        # Fields that a table calculation is computed along must be listed too.
        out += [f.table_calc_by for f in list(out) if f.table_calc_by is not None]
        unique = {}
        for f in out:
            unique.setdefault(f.local, f)
        return list(unique.values())


def categorical_all_filter(field, group):
    """'Keep all values' filter on a dimension, shared through filter-group."""
    xml = (f"          <filter class='categorical' column='{a(field.ref)}' filter-group='{group}'>\n"
           f"            <groupfilter function='level-members' level='{a(field.local)}' "
           "user:ui-enumeration='all' user:ui-marker='enumerate' />\n"
           "          </filter>")
    return (xml, field, True)


def date_range_filter(field, group, start, end):
    xml = (f"          <filter class='quantitative' column='{a(field.ref)}' filter-group='{group}' "
           "included-values='in-range'>\n"
           f"            <min>#{start}#</min>\n            <max>#{end}#</max>\n          </filter>")
    return (xml, field, True)


def rank_equals_one_filter(field):
    xml = (f"          <filter class='quantitative' column='{a(field.ref)}' included-values='in-range'>\n"
           "            <min>1</min>\n            <max>1</max>\n          </filter>")
    return (xml, field, False)


def worksheet_xml(sheet):
    ds = sheet.ds
    fields = sheet.fields()
    # List every column the sheet uses, plus the columns that its calculated
    # fields refer to (Tableau expects both in the dependency list).
    used_columns = {}
    pending = [f.column for f in fields]
    while pending:
        column = pending.pop()
        if column.name in used_columns:
            continue
        used_columns[column.name] = column
        for referenced in re.findall(r"\[([^\]]+)\]", column.formula or ""):
            if referenced in ds.by_name:
                pending.append(ds.by_name[referenced])
    column_defs = "\n".join(c.definition_xml("            ")
                            for c in sorted(used_columns.values(), key=lambda c: c.name))
    instances = "\n".join(f.instance_xml("            ")
                          for f in sorted(fields, key=lambda f: f.local))

    filters = "\n".join(xml for xml, _, _ in sheet.filters)
    sort = ""
    if sheet.sort:
        dim, measure, direction = sheet.sort
        sort = (f"\n          <computed-sort column='{a(dim.ref)}' direction='{direction}' "
                f"using='{a(measure.ref)}' />")
    slices = [f for _, f, is_slice in sheet.filters if is_slice]
    slices_xml = ""
    if slices:
        slices_xml = ("\n          <slices>\n" + "\n".join(
            f"            <column>{escape(f.ref)}</column>" for f in slices) + "\n          </slices>")

    title = ""
    if sheet.title_runs:
        title = ("      <layout-options>\n        <title>\n"
                 + formatted_text(sheet.title_runs, "          ")
                 + "\n        </title>\n      </layout-options>\n")

    encodings = "\n".join(f"              <{attr} column='{a(f.ref)}' />" for attr, f in sheet.encodings)
    encodings_xml = f"            <encodings>\n{encodings}\n            </encodings>\n" if encodings else ""

    tooltip = ""
    if sheet.tooltip_runs:
        tooltip = ("            <customized-tooltip>\n"
                   + formatted_text(sheet.tooltip_runs, "              ")
                   + "\n            </customized-tooltip>\n")
    label = ""
    if sheet.label_runs:
        label = ("            <customized-label>\n"
                 + formatted_text(sheet.label_runs, "              ")
                 + "\n            </customized-label>\n")

    rows = escape(sheet.rows.ref) if sheet.rows else ""
    cols = escape(sheet.cols.ref) if sheet.cols else ""
    rows_xml = f"<rows>{rows}</rows>" if rows else "<rows />"
    cols_xml = f"<cols>{cols}</cols>" if cols else "<cols />"
    table_style = f"        <style>\n{sheet.table_style}        </style>\n" if sheet.table_style else "        <style />\n"

    # The sheet's own data source must be listed first: Tableau treats the
    # first one as the primary source. Parameters goes second.
    params_source, params_deps = "", ""
    if sheet.uses_params:
        params_source = "            <datasource name='Parameters' />\n"
        params_deps = ("          <datasource-dependencies datasource='Parameters'>\n"
                       + "\n".join(prm.xml("            ") for prm in PARAMS)
                       + "\n          </datasource-dependencies>\n")

    return f"""    <worksheet name='{a(sheet.name)}'>
{title}      <table>
        <view>
          <datasources>
            <datasource caption='{a(ds.caption)}' name='{ds.name}' />
{params_source}          </datasources>
{params_deps}          <datasource-dependencies datasource='{ds.name}'>
{column_defs}
{instances}
          </datasource-dependencies>
{filters}{sort}{slices_xml}
          <aggregation value='true' />
        </view>
{table_style}        <panes>
          <pane selection-relaxation-option='selection-relaxation-allow'>
            <view>
              <breakdown value='auto' />
            </view>
            <mark class='{sheet.mark}' />
{encodings_xml}{tooltip}{label}            <style>
              <style-rule element='mark'>
                <format attr='mark-labels-show' value='{'true' if sheet.label_show else 'false'}' />
{sheet.mark_style}              </style-rule>
{sheet.pane_style}            </style>
          </pane>
        </panes>
        {rows_xml}
        {cols_xml}
      </table>
      <simple-id uuid='{stable_uuid('sheet:' + sheet.name)}' />
    </worksheet>"""


def title_runs(title, subtitle):
    return [run(title, size=12, color=INK, font="Tableau Semibold"), NEWLINE,
            run(subtitle, size=9, color=INK_2)]


def build_sheets(market, alloc, start_date, end_date):
    m = lambda name, d="None", **kw: Field(market, name, d, **kw)
    p = lambda name, d="None", **kw: Field(alloc, name, d, **kw)

    period = market.calcs[0].name
    date = m("Date")
    ticker, company, sector = m("Ticker"), m("Company"), m("Sector")
    # Text fields shown only in tooltips must be wrapped in ATTR().
    company_attr, sector_attr = m("Company", "Attribute"), m("Sector", "Attribute")
    close = m("Close", "Avg")
    period_return = m(period, "User")

    # The Company and Date filters are shared by every market sheet
    # (same filter-group number = one filter on the dashboard controls all).
    def shared_filters():
        return [member_filter(m(calc_name("In Stock Selection")), "Yes"),
                date_range_filter(m("Date"), 3, start_date, end_date)]

    # ---------------- Sheet 1: Stock Price Trend (line chart) ----------------
    price = Sheet(
        "Stock Price Trend", market, "Line",
        title_runs=title_runs("Stock Price Trend",
                              "Daily closing price (USD) · hover a line for OHLC, daily return and volume"),
        rows=close, cols=date,
        encodings=[("color", ticker), ("text", ticker), ("tooltip", company_attr),
                   ("tooltip", m("Open", "Avg")), ("tooltip", m("High", "Avg")),
                   ("tooltip", m("Low", "Avg")), ("tooltip", m("Daily_Return", "Avg")),
                   ("tooltip", m("Volume", "Sum"))],
        tooltip_runs=[
            run(field_tag(company_attr), size=10, color=INK, bold=True, raw=True),
            run(" (", size=10, color=INK_2), run(field_tag(ticker), size=10, color=INK_2, raw=True),
            run(")", size=10, color=INK_2),
            run("&#10;", raw=True), run(field_tag(date), size=9, color=INK_2, raw=True),
            run("&#10;Close:&#9;", size=9, color=INK_2, raw=True),
            run(field_tag(close), size=9, color=INK, bold=True, raw=True),
            run("&#10;Open / High / Low:&#9;", size=9, color=INK_2, raw=True),
            run(field_tag(m("Open", "Avg")), size=9, color=INK, raw=True), run(" / ", size=9),
            run(field_tag(m("High", "Avg")), size=9, color=INK, raw=True), run(" / ", size=9),
            run(field_tag(m("Low", "Avg")), size=9, color=INK, raw=True),
            run("&#10;Daily return:&#9;", size=9, color=INK_2, raw=True),
            run(field_tag(m("Daily_Return", "Avg")), size=9, color=INK, bold=True, raw=True),
            run("&#10;Volume:&#9;", size=9, color=INK_2, raw=True),
            run(field_tag(m("Volume", "Sum")), size=9, color=INK, raw=True),
        ],
        label_runs=[run(field_tag(ticker), size=9, color=INK_2, bold=True, raw=True)],
        filters=shared_filters(),
        table_style=(
            "          <style-rule element='axis'>\n"
            f"            <format attr='title' class='0' field='{a(close.ref)}' scope='rows' value='Closing price (USD)' />\n"            f"            <format attr='title' class='0' field='{a(date.ref)}' scope='cols' value='' />\n"
            "          </style-rule>\n"
            "          <style-rule element='gridline'>\n"
            "            <format attr='line-visibility' scope='cols' value='off' />\n"
            "          </style-rule>\n"),
        mark_style=("                <format attr='mark-labels-cull' value='true' />\n"
                    "                <format attr='mark-labels-mode' value='line-ends' />\n"
                    "                <format attr='mark-labels-line-first' value='false' />\n"
                    "                <format attr='mark-labels-line-last' value='true' />\n"),
    )

    # ------------- Sheet 2: Stock Return Comparison (bar chart) --------------
    returns = Sheet(
        "Stock Return Comparison", market, "Bar",
        title_runs=title_runs("Stock Return Comparison",
                              "Cumulative total return over the selected dates (dividends included)"),
        rows=company, cols=period_return,
        encodings=[("color", ticker), ("text", period_return), ("tooltip", sector_attr)],
        tooltip_runs=[
            run(field_tag(company), size=10, color=INK, bold=True, raw=True),
            run(" (", size=10, color=INK_2), run(field_tag(ticker), size=10, color=INK_2, raw=True),
            run(")", size=10, color=INK_2),
            run("&#10;Sector:&#9;", size=9, color=INK_2, raw=True),
            run(field_tag(sector_attr), size=9, color=INK, raw=True),
            run("&#10;Cumulative return:&#9;", size=9, color=INK_2, raw=True),
            run(field_tag(period_return), size=9, color=INK, bold=True, raw=True),
            run("&#10;Product of (1 + daily return) − 1 over the selected dates", size=8, color=INK_3,
                raw=True),
        ],
        label_runs=[run(field_tag(period_return), size=9, color=INK, bold=True, raw=True)],
        filters=shared_filters(),
        sort=(company, period_return, "DESC"),
        table_style=(
            "          <style-rule element='axis'>\n"
            f"            <format attr='title' class='0' field='{a(period_return.ref)}' scope='cols' value='Cumulative return' />\n"            "          </style-rule>\n"
            "          <style-rule element='header'>\n"
            f"            <format attr='width' field='{a(company.ref)}' value='205' />\n"
            "          </style-rule>\n"
            "          <style-rule element='worksheet'>\n"
            "            <format attr='display-field-labels' scope='rows' value='false' />\n"
            "          </style-rule>\n"
            "          <style-rule element='gridline'>\n"
            "            <format attr='line-visibility' scope='rows' value='off' />\n"
            "          </style-rule>\n"),
        mark_style="                <format attr='size' value='0.6' />\n",
    )

    # -------------- Sheet 3: Portfolio Allocation (treemap) ------------------
    p_company, p_ticker = p("Company"), p("Ticker")
    amount = p("Investment_Amount", "Sum")
    share = p(alloc.calcs[0].name, "User")
    allocation = Sheet(
        "Portfolio Allocation", alloc, "Square",
        title_runs=title_runs("Portfolio Allocation",
                              "Amount invested per company · SAMPLE / DEMO holdings bought on the first trading day"),
        encodings=[("size", amount), ("color", p_ticker), ("lod", p_company), ("text", p_ticker),
                   ("text", amount), ("text", share),
                   ("tooltip", p("Sector", "Attribute")), ("tooltip", p("Quantity", "Sum")),
                   ("tooltip", p("Purchase_Price", "Avg")), ("tooltip", p("Data_Label", "Attribute"))],
        tooltip_runs=[
            run(field_tag(p_company), size=10, color=INK, bold=True, raw=True),
            run(" (", size=10, color=INK_2), run(field_tag(p_ticker), size=10, color=INK_2, raw=True),
            run(")", size=10, color=INK_2),
            run("&#10;Sector:&#9;", size=9, color=INK_2, raw=True),
            run(field_tag(p("Sector", "Attribute")), size=9, color=INK, raw=True),
            run("&#10;Quantity × price:&#9;", size=9, color=INK_2, raw=True),
            run(field_tag(p("Quantity", "Sum")), size=9, color=INK, raw=True),
            run(" × ", size=9, color=INK_2),
            run(field_tag(p("Purchase_Price", "Avg")), size=9, color=INK, raw=True),
            run("&#10;Amount invested:&#9;", size=9, color=INK_2, raw=True),
            run(field_tag(amount), size=9, color=INK, bold=True, raw=True),
            run("&#10;Share of portfolio:&#9;", size=9, color=INK_2, raw=True),
            run(field_tag(share), size=9, color=INK, bold=True, raw=True),
            run("&#10;", raw=True),
            run(field_tag(p("Data_Label", "Attribute")), size=8, color=INK_3, raw=True),
        ],
        # Tickers keep labels readable in small tiles; the tooltip has the full name.
        label_runs=[
            run(field_tag(p_ticker), size=10, color=INK, bold=True, raw=True), NEWLINE,
            run(field_tag(amount), size=9, color=INK, raw=True), NEWLINE,
            run(field_tag(share), size=9, color=INK, raw=True),
        ],
    )

    # ----------------------- KPI tiles (hidden sheets) -----------------------
    def kpi(name, ds, caption, value_runs, encodings, filters=(), value_size=None):
        runs = [run(caption, size=8, color=INK_3, bold=True), NEWLINE] + value_runs
        return Sheet(name, ds, "Text", encodings=encodings, label_runs=runs,
                     filters=filters, hidden=True,
                     pane_style=("              <style-rule element='cell'>\n"
                                 "                <format attr='text-align' value='left' />\n"
                                 "              </style-rule>\n"),
                     tooltip_runs=[run(caption.title(), size=9, color=INK_2)])

    stocks = m(market.calcs[1].name, "User")
    sectors = m(market.calcs[2].name, "User")
    days = m(market.calcs[3].name, "User")
    date_range = m(market.calcs[4].name, "User")
    rank_best = m(market.calcs[5].name, "User", table_calc_by=m("Company"))
    rank_worst = m(market.calcs[6].name, "User", table_calc_by=m("Company"))
    holdings = p(alloc.calcs[1].name, "User")

    kpi_stocks = kpi(
        "KPI Stocks", market, "STOCKS TRACKED",
        [run(field_tag(stocks), size=18, color=INK, bold=True, raw=True), NEWLINE,
         run("across ", size=9, color=INK_2), run(field_tag(sectors), size=9, color=INK_2, raw=True),
         run(" sectors", size=9, color=INK_2)],
        [("text", stocks), ("text", sectors)], shared_filters())
    kpi_days = kpi(
        "KPI Trading Days", market, "TRADING DAYS ANALYSED",
        [run(field_tag(days), size=18, color=INK, bold=True, raw=True), NEWLINE,
         run(field_tag(date_range), size=9, color=INK_2, raw=True)],
        [("text", days), ("text", date_range)], shared_filters())
    kpi_best = kpi(
        "KPI Best Performer", market, "BEST PERFORMER",
        [run(field_tag(company), size=12, color=INK, bold=True, raw=True), NEWLINE,
         run(field_tag(period_return), size=11, color=GAIN, bold=True, raw=True),
         run(" total return", size=9, color=INK_2)],
        [("text", company), ("text", period_return)],
        shared_filters() + [rank_equals_one_filter(rank_best)])
    kpi_worst = kpi(
        "KPI Weakest Performer", market, "WEAKEST PERFORMER",
        [run(field_tag(company), size=12, color=INK, bold=True, raw=True), NEWLINE,
         run(field_tag(period_return), size=11, color=LOSS, bold=True, raw=True),
         run(" total return", size=9, color=INK_2)],
        [("text", company), ("text", period_return)],
        shared_filters() + [rank_equals_one_filter(rank_worst)])
    kpi_invested = kpi(
        "KPI Sample Invested", alloc, "SAMPLE PORTFOLIO INVESTED",
        [run(field_tag(amount), size=18, color=INK, bold=True, raw=True), NEWLINE,
         run(field_tag(holdings), size=9, color=INK_2, raw=True),
         run(" holdings · ", size=9, color=INK_2),
         run(field_tag(p("Data_Label", "Attribute")), size=9, color=LOSS, bold=True, raw=True)],
        [("text", amount), ("text", holdings), ("text", p("Data_Label", "Attribute"))])

    sheets = [price, returns, allocation, kpi_stocks, kpi_days, kpi_best, kpi_worst, kpi_invested]
    for sheet in sheets:
        if sheet.ds is market:
            sheet.uses_params = True    # the Stock selection reads a parameter
    return sheets


# ---------------------------------------------------------------------------
# Dashboards
# ---------------------------------------------------------------------------
# Each dashboard is a fixed grid: every object is placed at an exact pixel
# rectangle inside one tiled container, and the rectangles cover the whole
# dashboard with no overlaps. Gaps between cards come from zone margins.
# Tableau stores positions in units of 1/100000 of the dashboard size.
class Zones:
    """Hands out unique zone ids and converts pixel boxes to Tableau units."""

    def __init__(self):
        self.next_id = 1

    def new_id(self):
        self.next_id += 1
        return self.next_id

    @staticmethod
    def box(x, y, w, h):
        return (f"h='{round(h / DASH_H * 100000)}' w='{round(w / DASH_W * 100000)}' "
                f"x='{round(x / DASH_W * 100000)}' y='{round(y / DASH_H * 100000)}'")


def zone_style(margins=(0, 0, 0, 0), padding=0, bg=None, border=None, border_style="solid",
               indent="            "):
    """Card styling: margins are (left, top, right, bottom) in pixels."""
    left, top, right, bottom = margins
    rows = []
    if border:
        rows += [f"<format attr='border-color' value='{border}' />",
                 f"<format attr='border-style' value='{border_style}' />",
                 "<format attr='border-width' value='1' />"]
    else:
        rows += ["<format attr='border-color' value='#000000' />",
                 "<format attr='border-style' value='none' />",
                 "<format attr='border-width' value='0' />"]
    rows += [f"<format attr='margin-left' value='{left}' />",
             f"<format attr='margin-top' value='{top}' />",
             f"<format attr='margin-right' value='{right}' />",
             f"<format attr='margin-bottom' value='{bottom}' />",
             f"<format attr='padding' value='{padding}' />"]
    if bg:
        rows.append(f"<format attr='background-color' value='{bg}' />")
    inner = "\n".join(f"{indent}  {r}" for r in rows)
    return f"{indent}<zone-style>\n{inner}\n{indent}</zone-style>"


def place(z, rect, attrs="", runs=None, margins=(0, 0, 0, 0), padding=8, bg=CARD_BG,
          border=None, border_style="solid"):
    """One dashboard object (sheet, filter, legend or text box) at a pixel box."""
    indent = "          "
    attrs = f" {attrs}" if attrs else ""
    body = (formatted_text(runs, indent + "  ") + "\n") if runs else ""
    style = zone_style(margins, padding, bg, border, border_style, indent + "  ")
    return (f"{indent}<zone {Zones.box(*rect)} id='{z.new_id()}'{attrs}>\n"
            f"{body}{style}\n{indent}</zone>")


def dashboard_xml(name, zones, datasource=None, dependencies="", sources_xml=""):
    sources = sources_xml
    if datasource is not None:
        sources = (f"      <datasources>\n        <datasource caption='{a(datasource.caption)}' "
                   f"name='{datasource.name}' />\n      </datasources>\n"
                   f"      <datasource-dependencies datasource='{datasource.name}'>\n"
                   f"{dependencies}\n      </datasource-dependencies>\n")
    root_style = zone_style(bg=PAGE_BG, indent="          ")
    return f"""    <dashboard enable-sort-zone-taborder='true' name='{a(name)}'>
      <style />
      <size sizing-mode='automatic' />
{sources}      <zones>
        <zone h='100000' id='1' type-v2='layout-basic' w='100000' x='0' y='0'>
{chr(10).join(zones)}
{root_style}
        </zone>
      </zones>
      <simple-id uuid='{stable_uuid('dash:' + name)}' />
    </dashboard>"""


HEADER_H = 72


def header_zone(z, title, subtitle):
    return place(z, (0, 0, DASH_W, HEADER_H), "type-v2='text'", [
        run(title, size=17, color="#ffffff", font="Tableau Semibold"), NEWLINE,
        run(subtitle, size=9, color=HEADER_SUB)], padding=10, bg=HEADER_BG)


def main_dashboard_xml(market, name):
    z = Zones()
    date = Field(market, "Date")
    ticker = Field(market, "Ticker")
    zones = [header_zone(
        z, "Investment Portfolio & Market Analytics",
        "Market overview · 6 US stocks across 6 sectors · daily prices from Yahoo Finance (USD) · "
        "portfolio holdings are SAMPLE / DEMO data")]

    # KPI row: five tiles across the full width.
    kpi_names = ["KPI Stocks", "KPI Trading Days", "KPI Best Performer",
                 "KPI Weakest Performer", "KPI Sample Invested"]
    edges = [round(i * DASH_W / 5) for i in range(6)]
    for i, sheet_name in enumerate(kpi_names):
        margins = (12 if i == 0 else 6, 12, 12 if i == 4 else 6, 6)
        zones.append(place(z, (edges[i], HEADER_H, edges[i + 1] - edges[i], 96),
                           f"name='{a(sheet_name)}' show-title='false'", margins=margins, padding=4))

    # Charts: price trend on top, return comparison and allocation below.
    top, mid = HEADER_H + 96, HEADER_H + 96 + 304          # 160, 464
    zones.append(place(z, (0, top, 1088, 304), "name='Stock Price Trend'", margins=(12, 6, 6, 6)))
    zones.append(place(z, (0, mid, 544, 304), "name='Stock Return Comparison'", margins=(12, 6, 6, 12)))
    zones.append(place(z, (544, mid, 544, 304), "name='Portfolio Allocation'", margins=(6, 6, 6, 12)))

    # Sidebar: filters, colour legend and notes stacked as one white column.
    sx, sw = 1088, DASH_W - 1088
    side = [
        (36, "type-v2='text'", [run("FILTERS", size=9, color=INK_3, bold=True)]),
        (70, f"mode='compact' param='{a(P_STOCK.ref)}' type-v2='paramctrl'", None),
        (84, f"name='Stock Price Trend' param='{a(date.ref)}' type-v2='filter'", None),
        (150, f"name='Stock Price Trend' pane-specification-id='0' param='{a(ticker.ref)}' type-v2='color'",
         None),
        (DASH_H - top - 36 - 70 - 84 - 150, "type-v2='text'", [
            run("ABOUT THE DATA", size=8, color=INK_3, bold=True), NEWLINE,
            run("• Yahoo Finance daily prices (USD).", size=8, color=INK_2), NEWLINE,
            run("• Returns use adjusted close (dividends included).", size=8, color=INK_2), NEWLINE,
            run("• Stock and Date drive the market charts and KPIs.", size=8, color=INK_2), NEWLINE,
            run("• Click any stock to highlight it everywhere.", size=8, color=INK_2),
        ]),
    ]
    y = top
    for i, (height, attrs, runs) in enumerate(side):
        margins = (6, 6 if i == 0 else 0, 12, 12 if i == len(side) - 1 else 0)
        zones.append(place(z, (sx, y, sw, height), attrs, runs, margins=margins, padding=8))
        y += height

    sources = (
        "      <datasources>\n        <datasource name='Parameters' />\n"
        f"        <datasource caption='{a(market.caption)}' name='{market.name}' />\n      </datasources>\n"
        "      <datasource-dependencies datasource='Parameters'>\n"
        + P_STOCK.xml("        ") + "\n      </datasource-dependencies>\n"
        f"      <datasource-dependencies datasource='{market.name}'>\n"
        "        <column datatype='date' name='[Date]' role='dimension' type='ordinal' />\n"
        "        <column datatype='string' name='[Ticker]' role='dimension' type='nominal' />\n"
        + date.instance_xml("        ") + "\n" + ticker.instance_xml("        ")
        + "\n      </datasource-dependencies>\n")
    return dashboard_xml(name, zones, sources_xml=sources)


# ---------------------------------------------------------------------------
# Actions and windows
# ---------------------------------------------------------------------------
def actions_xml(dashboard_names):
    # Clicking a stock on any chart highlights the same Ticker everywhere on
    # that dashboard, even on charts that use a different data source.
    out = []
    for k, dashboard_name in enumerate(dashboard_names, start=1):
        seed = "action" if k == 1 else f"action:{dashboard_name}"
        out.append(f"""    <action caption='Highlight selected stock ({a(dashboard_name)})' name='[Action{k}_{stable_id(seed, 32).upper()}]'>
      <activation auto-clear='true' type='on-select' />
      <source dashboard='{a(dashboard_name)}' type='sheet' />
      <command command='tsc:brush'>
        <param name='field-captions' value='Ticker' />
        <param name='target' value='{a(dashboard_name)}' />
      </command>
    </action>""")
    return "  <actions>\n" + "\n".join(out) + "\n  </actions>"


CARDS = """      <cards>
        <edge name='left'>
          <strip size='160'>
            <card type='pages' />
            <card type='filters' />
            <card type='marks' />
          </strip>
        </edge>
        <edge name='top'>
          <strip size='2147483647'>
            <card type='columns' />
          </strip>
          <strip size='2147483647'>
            <card type='rows' />
          </strip>
          <strip size='31'>
            <card type='title' />
          </strip>
        </edge>
      </cards>"""


def windows_xml(dashboards, sheets, main_dashboard):
    out = []
    for name, sheet_names in dashboards:
        maximized = " maximized='true'" if name == main_dashboard else ""
        viewpoints = "\n".join(
            f"        <viewpoint name='{a(s)}'>\n          <zoom type='entire-view' />\n        </viewpoint>"
            for s in sheet_names)
        vp = f"      <viewpoints>\n{viewpoints}\n      </viewpoints>\n" if sheet_names else "      <viewpoints />\n"
        out.append(f"""    <window class='dashboard'{maximized} name='{a(name)}'>
{vp}      <active id='-1' />
      <simple-id uuid='{stable_uuid('win:' + name)}' />
    </window>""")
    for sheet in sheets:
        # Every worksheet sits on a dashboard, so all are hidden: the tab bar
        # shows only the four dashboards. (Right-click a dashboard tab and
        # choose Unhide All Sheets to see them.)
        hidden = " hidden='true'"
        out.append(f"""    <window class='worksheet'{hidden} name='{a(sheet.name)}'>
{CARDS}
      <simple-id uuid='{stable_uuid('win:' + sheet.name)}' />
    </window>""")
    return "  <windows source-height='72'>\n" + "\n".join(out) + "\n  </windows>"


# ===========================================================================
# PHASES 3-12: portfolio performance, risk, benchmark and goal simulator
# ===========================================================================
HOLDINGS_CSV = "tableau_portfolio_holdings.csv"
SUMMARY_CSV = "tableau_portfolio_summary.csv"
SECTOR_CSV = "tableau_sector_exposure.csv"
RISK_CSV = "tableau_risk_return.csv"
BENCHMARK_CSV = "tableau_benchmark_comparison.csv"
GOAL_CSV = "tableau_goal_scaffold.csv"
ALL_CSVS = [MARKET_CSV, ALLOCATION_CSV, HOLDINGS_CSV, SUMMARY_CSV, SECTOR_CSV, RISK_CSV,
            BENCHMARK_CSV, GOAL_CSV]

PCT1 = "p0.0%"
PCT_SIGNED_USD = '*+"$"#,##0;-"$"#,##0;"$"0'
INR = '*"₹"#,##0;-"₹"#,##0'
RATIO = "n0.00;-0.00"
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

RISK_COLOURS = {"Low": "#1baf7a", "Medium": "#eda100", "High": "#e34948", "Benchmark": "#52514e"}
BENCH_COLOURS = {"Sample Portfolio": "#2a78d6", "S&P 500": "#898781"}
GOAL_COLOURS = {"Projected Value": "#2a78d6", "Total Contributions": "#898781",
                "Target Amount": "#e34948"}


def infer_columns(filename, formats=None, captions=None, aggs=None, dimensions=()):
    """Build Column objects from a CSV header, guessing each column's type."""
    formats, captions, aggs = formats or {}, captions or {}, aggs or {}
    rows = read_csv_rows(filename)
    columns = []
    for name in rows[0].keys():
        values = [r[name] for r in rows if r[name] != ""]
        if values and all(DATE_RE.match(v) for v in values):
            datatype = "date"
        elif values and all(re.fullmatch(r"-?\d+", v) for v in values):
            datatype = "integer"
        elif values and all(re.fullmatch(r"-?\d+(\.\d+)?([eE]-?\d+)?", v) for v in values):
            datatype = "real"
        else:
            datatype = "string"
        role = "dimension" if name in dimensions else None
        ctype = "quantitative" if name in dimensions and datatype in ("integer", "real") else None
        columns.append(Column(name, datatype, captions.get(name, name.replace("_", " ")),
                              fmt=formats.get(name), agg=aggs.get(name), role=role, ctype=ctype))
    return columns


def calc(caption, datatype, formula, fmt=None, role=None, ctype=None):
    return Column(calc_name(caption), datatype, caption, fmt=fmt, formula=formula, role=role,
                  ctype=ctype)


# ----------------------------- Parameters -----------------------------------
class Param:
    """A Tableau parameter (range slider), used by the Goal Simulator."""

    def __init__(self, number, caption, datatype, value, low, high, step, fmt):
        self.name = f"Parameter {number}"
        self.caption, self.datatype = caption, datatype
        self.value, self.low, self.high, self.step, self.fmt = value, low, high, step, fmt

    @property
    def ref(self):
        return f"[Parameters].[{self.name}]"

    def _v(self, x):
        return str(int(x)) if self.datatype == "integer" else repr(float(x))

    def xml(self, indent):
        v = self._v(self.value)
        return (f"{indent}<column caption='{a(self.caption)}' datatype='{self.datatype}' "
                f"default-format='{a(self.fmt)}' name='[{self.name}]' param-domain-type='range' "
                f"role='measure' type='quantitative' value='{v}'>\n"
                f"{indent}  <calculation class='tableau' formula='{v}' />\n"
                f"{indent}  <range granularity='{self._v(self.step)}' max='{self._v(self.high)}' "
                f"min='{self._v(self.low)}' />\n{indent}</column>")


P_INITIAL = Param(1, "Initial Investment (₹)", "real", 200000, 0, 5000000, 10000, INR)
P_MONTHLY = Param(2, "Monthly Investment / SIP (₹)", "real", 5000, 0, 200000, 500, INR)
P_TARGET = Param(3, "Target Amount (₹)", "real", 1000000, 100000, 20000000, 50000, INR)
P_RETURN = Param(4, "Expected Annual Return (%)", "real", 12, 0, 30, 0.5, 'n0.0"%"')
P_YEARS = Param(5, "Investment Period (years)", "integer", 5, 1, 40, 1, 'n0" yrs"')
GOAL_PARAMS = [P_INITIAL, P_MONTHLY, P_TARGET, P_RETURN, P_YEARS]


class ListParam:
    """A Tableau parameter with a fixed list of text values (a drop-down)."""

    def __init__(self, number, caption, default, values_fn):
        self.name = f"Parameter {number}"
        self.caption, self.default, self.values_fn = caption, default, values_fn

    @property
    def ref(self):
        return f"[Parameters].[{self.name}]"

    def xml(self, indent):
        values = [self.default] + list(self.values_fn())
        members = "\n".join(f"{indent}    <member value='&quot;{a(v)}&quot;' />" for v in values)
        return (f"{indent}<column caption='{a(self.caption)}' datatype='string' name='[{self.name}]' "
                f"param-domain-type='list' role='measure' type='nominal' value='&quot;{a(self.default)}&quot;'>\n"
                f"{indent}  <calculation class='tableau' formula='&quot;{a(self.default)}&quot;' />\n"
                f"{indent}  <members>\n{members}\n{indent}  </members>\n{indent}</column>")


P_STOCK = ListParam(6, "Stock", ALL_STOCKS,
                    lambda: sorted({row["Company"] for row in read_csv_rows(MARKET_CSV)}))
assert P_STOCK.ref == STOCK_PARAM_REF
PARAMS = GOAL_PARAMS + [P_STOCK]


def parameters_datasource_xml():
    cols = "\n".join(prm.xml("      ") for prm in PARAMS)
    return (f"    <datasource hasconnection='false' inline='true' name='Parameters' version='18.1'>\n"
            f"      <aliases enabled='yes' />\n{cols}\n    </datasource>")


# ----------------------------- Data sources ---------------------------------
def build_holdings_source(tickers):
    columns = infer_columns(HOLDINGS_CSV, formats={
        "Purchase_Price": USD, "Investment_Amount": USD0, "Latest_Close": USD,
        "Current_Value": USD0, "Profit_Loss": PCT_SIGNED_USD, "Return_Percentage": PCT_SIGNED,
        "Investment_Weight": PCT1, "Portfolio_Weight": PCT1, "Quantity": COUNT},
        aggs={"Purchase_Price": "Avg", "Latest_Close": "Avg", "Return_Percentage": "Avg"})
    calcs = [calc("Holding Return", "real",
                  "SUM([Profit_Loss]) / SUM([Investment_Amount])", PCT_SIGNED)]
    palette = {t: SERIES_COLOURS[i % len(SERIES_COLOURS)] for i, t in enumerate(tickers)}
    return DataSource("Portfolio Holdings (Sample)", HOLDINGS_CSV, columns, calcs, "Ticker", palette)


def build_summary_source():
    pct_cols = ["Portfolio_Return", "Best_Asset_Return", "Worst_Asset_Return",
                "Largest_Holding_Weight", "Portfolio_Growth_vs_Start", "Benchmark_Growth",
                "Excess_Return_vs_Benchmark", "Most_Volatile_Value", "Least_Volatile_Value",
                "Deepest_Drawdown_Value", "Benchmark_Volatility", "Benchmark_Max_Drawdown"]
    formats = {c: PCT_SIGNED for c in pct_cols}
    formats.update({c: PCT1 for c in ["Largest_Holding_Weight", "Most_Volatile_Value",
                                       "Least_Volatile_Value", "Benchmark_Volatility"]})
    formats.update({"Total_Investment": USD0, "Current_Value": USD0,
                    "Total_Profit_Loss": PCT_SIGNED_USD, "HHI_Holdings": "n0.000",
                    "HHI_Sectors": "n0.000", "Effective_Holdings": "n0.0",
                    "Best_Sharpe_Value": RATIO})
    return DataSource("Portfolio Summary", SUMMARY_CSV, infer_columns(SUMMARY_CSV, formats))


def build_sector_source():
    columns = infer_columns(SECTOR_CSV, formats={
        "Investment_Amount": USD0, "Current_Value": USD0, "Profit_Loss": PCT_SIGNED_USD,
        "Return_Percentage": PCT_SIGNED, "Sector_Weight": PCT1})
    # One colour for every sector, set as a palette on Sector (a fixed mark
    # colour on the sheet renders as a checkerboard in Tableau 2026.3).
    sectors = sorted({row["Sector"] for row in read_csv_rows(SECTOR_CSV)})
    return DataSource("Sector Exposure", SECTOR_CSV, columns, (), "Sector",
                      {name: "#4a3aa7" for name in sectors})


def build_risk_source():
    columns = infer_columns(RISK_CSV, formats={
        "Annualized_Return": PCT_SIGNED, "Annualized_Volatility": PCT1, "Sharpe_Ratio": RATIO,
        "Max_Drawdown": PCT_SIGNED, "Total_Return": PCT_SIGNED, "Risk_Free_Rate": PCT1},
        aggs={c: "Avg" for c in ["Annualized_Return", "Annualized_Volatility", "Sharpe_Ratio",
                                  "Max_Drawdown", "Total_Return", "Risk_Free_Rate"]})
    return DataSource("Risk and Return", RISK_CSV, columns, (), "Risk_Group", RISK_COLOURS)


def build_benchmark_source():
    columns = infer_columns(BENCHMARK_CSV, formats={"Index_Value": "n0.0", "Value_USD": USD},
                            captions={"Index_Value": "Growth of 100",
                                      "Value_USD": "Value (USD or index points)"},
                            aggs={"Index_Value": "Avg", "Value_USD": "Avg"})
    return DataSource("Benchmark Comparison", BENCHMARK_CSV, columns, (), "Series", BENCH_COLOURS)


def build_goal_source():
    columns = infer_columns(GOAL_CSV, dimensions=("Year",))
    P, PMT, T, R, N = (prm.ref for prm in GOAL_PARAMS)
    fv_init = calc("FV of Initial (Year)", "real", f"{P} * POWER(1 + {R} / 100, [Year])", INR)
    fv_sip = calc("FV of SIP (Year)", "real",
                  f"IIF({R} = 0, {PMT} * 12 * [Year], "
                  f"{PMT} * (POWER(1 + {R} / 1200, 12 * [Year]) - 1) / ({R} / 1200))", INR)
    projected_y = calc("Projected Value (Year)", "real",
                       f"[{fv_init.name}] + [{fv_sip.name}]", INR)
    contrib_y = calc("Total Contributions (Year)", "real", f"{P} + {PMT} * 12 * [Year]", INR)
    amount = calc("Projection Amount", "real",
                  f"CASE [Series] WHEN 'Projected Value' THEN [{projected_y.name}] "
                  f"WHEN 'Total Contributions' THEN [{contrib_y.name}] ELSE {T} END", INR)
    in_period = calc("In Investment Period", "string", f"IIF([Year] <= {N}, 'Yes', 'No')")
    final_year = calc("Is Final Year", "string", f"IIF([Year] = {N}, 'Yes', 'No')")

    fv_init_n = f"{P} * POWER(1 + {R} / 100, {N})"
    sip_factor_n = f"IIF({R} = 0, 12 * {N}, (POWER(1 + {R} / 1200, 12 * {N}) - 1) / ({R} / 1200))"
    projected = calc("Projected Portfolio Value", "real",
                     f"{fv_init_n} + {PMT} * {sip_factor_n}", INR)
    contrib = calc("Total Contributions", "real", f"{P} + {PMT} * 12 * {N}", INR)
    growth = calc("Estimated Investment Growth", "real",
                  f"[{projected.name}] - [{contrib.name}]", INR)
    gap = calc("Goal Gap", "real", f"{T} - [{projected.name}]",
               '*"₹"#,##0" short";"₹"#,##0" surplus";"On target"')
    achievement = calc("Goal Achievement %", "real", f"[{projected.name}] / {T}", "p0.0%")
    required = calc("Required Monthly Investment", "real",
                    f"IIF({T} - {fv_init_n} <= 0, 0, ({T} - {fv_init_n}) / {sip_factor_n})", INR)
    status = calc("Goal Status", "string",
                  f"IIF([{projected.name}] >= {T}, 'Goal achieved', 'Not yet achieved')")
    calcs = [fv_init, fv_sip, projected_y, contrib_y, amount, in_period, final_year,
             projected, contrib, growth, gap, achievement, required, status]
    return DataSource("Goal Simulator", GOAL_CSV, columns, calcs, "Series", GOAL_COLOURS)


# ------------------------------- Sheets -------------------------------------
def text_tile(name, ds, caption, value_runs, encodings, filters=(), uses_params=False):
    """A KPI tile: small caps caption above one or two lines of values."""
    runs = [run(caption, size=8, color=INK_3, bold=True), NEWLINE] + value_runs
    return Sheet(name, ds, "Text", encodings=encodings, label_runs=runs, filters=filters,
                 hidden=True, uses_params=uses_params,
                 pane_style=("              <style-rule element='cell'>\n"
                             "                <format attr='text-align' value='left' />\n"
                             "              </style-rule>\n"),
                 tooltip_runs=[run(caption.title(), size=9, color=INK_2)])


def member_filter(field, value):
    xml = (f"          <filter class='categorical' column='{a(field.ref)}'>\n"
           f"            <groupfilter function='member' level='{a(field.local)}' "
           f"member='&quot;{a(value)}&quot;' user:ui-domain='database' "
           "user:ui-enumeration='inclusive' user:ui-marker='enumerate' />\n"
           "          </filter>")
    return (xml, field, True)


def no_row_grid(header_field, width):
    return ("          <style-rule element='header'>\n"
            f"            <format attr='width' field='{a(header_field.ref)}' value='{width}' />\n"
            "          </style-rule>\n"
            "          <style-rule element='worksheet'>\n"
            "            <format attr='display-field-labels' scope='rows' value='false' />\n"
            "          </style-rule>\n"
            "          <style-rule element='gridline'>\n"
            "            <format attr='line-visibility' scope='rows' value='off' />\n"
            "          </style-rule>\n")


def axis_title(field, scope, title):
    return (f"            <format attr='title' class='0' field='{a(field.ref)}' scope='{scope}' "
            f"value='{a(title)}' />\n")


def tip(label, field, bold=False):
    return [run(f"&#10;{label}:&#9;", size=9, color=INK_2, raw=True),
            run(field_tag(field), size=9, color=INK, bold=bold, raw=True)]


def big(field, size=18, color=INK):
    return run(field_tag(field), size=size, color=color, bold=True, raw=True)


def small(text_or_field, color=INK_2, bold=False):
    if isinstance(text_or_field, Field):
        return run(field_tag(text_or_field), size=9, color=color, bold=bold, raw=True)
    return run(text_or_field, size=9, color=color, bold=bold)


def build_phase3_to_12_sheets(hold, summ, sect, risk, bench, goal):
    h = lambda n, d="None", **kw: Field(hold, n, d, **kw)
    s = lambda n, d="Sum": Field(summ, n, d)
    sa = lambda n: Field(summ, n, "Attribute")
    sc = lambda n, d="None": Field(sect, n, d)
    r = lambda n, d="None": Field(risk, n, d)
    b = lambda n, d="None": Field(bench, n, d)
    g = lambda n, d="None": Field(goal, n, d)
    gc = lambda caption, d="Min": Field(goal, calc_name(caption), d)
    sheets = []

    # ------------------- Portfolio Performance (Phases 3, 5, 6) -------------------
    company, ticker = h("Company"), h("Ticker")
    # One row per holding, so SUM of the stored return is that holding's return.
    pl, ret = h("Profit_Loss", "Sum"), h("Return_Percentage", "Sum")
    invested, current = h("Investment_Amount", "Sum"), h("Current_Value", "Sum")
    sheets.append(Sheet(
        "Profit and Loss by Holding", hold, "Bar",
        title_runs=title_runs("Profit / Loss by Holding",
                              "Current value (latest close × quantity) minus amount invested · USD"),
        rows=company, cols=pl,
        encodings=[("color", ticker), ("text", pl), ("text", ret), ("tooltip", invested),
                   ("tooltip", current), ("tooltip", h("Portfolio_Weight", "Sum")),
                   ("tooltip", h("Latest_Close", "Avg"))],
        tooltip_runs=[run(field_tag(company), size=10, color=INK, bold=True, raw=True)]
        + tip("Invested", invested) + tip("Current value", current, True)
        + tip("Profit / loss", pl, True) + tip("Return", ret, True)
        + tip("Latest close", h("Latest_Close", "Avg")) + tip("Weight", h("Portfolio_Weight", "Sum")),
        label_runs=[run(field_tag(pl), size=9, color=INK, bold=True, raw=True),
                    run("  (", size=9, color=INK_2), run(field_tag(ret), size=9, color=INK_2, raw=True),
                    run(")", size=9, color=INK_2)],
        sort=(company, pl, "DESC"),
        table_style=("          <style-rule element='axis'>\n" + axis_title(pl, "cols", "Profit / loss (USD)")
                     + "          </style-rule>\n" + no_row_grid(company, 190)),
        mark_style="                <format attr='size' value='0.6' />\n"))

    sector = sc("Sector")
    weight, s_value = sc("Sector_Weight", "Sum"), sc("Current_Value", "Sum")
    sheets.append(Sheet(
        "Sector Exposure", sect, "Bar",
        title_runs=title_runs("Sector Exposure", "Share of current portfolio value by sector"),
        rows=sector, cols=weight,
        encodings=[("color", sector), ("text", weight), ("tooltip", s_value), ("tooltip", sc("Profit_Loss", "Sum")),
                   ("tooltip", sc("Return_Percentage", "Sum"))],
        tooltip_runs=[run(field_tag(sector), size=10, color=INK, bold=True, raw=True)]
        + tip("Weight", weight, True) + tip("Current value", s_value)
        + tip("Profit / loss", sc("Profit_Loss", "Sum")) + tip("Return", sc("Return_Percentage", "Sum")),
        label_runs=[run(field_tag(weight), size=9, color=INK, bold=True, raw=True)],
        sort=(sector, weight, "DESC"),
        table_style=("          <style-rule element='axis'>\n" + axis_title(weight, "cols", "Share of portfolio value")
                     + "          </style-rule>\n" + no_row_grid(sector, 140)),
        mark_style="                <format attr='size' value='0.6' />\n"))

    date, series = b("Date"), b("Series")
    index = b("Index_Value", "Avg")
    sheets.append(Sheet(
        "Portfolio vs S&P 500", bench, "Line",
        title_runs=title_runs("Portfolio vs S&P 500",
                              "Growth of 100 since the purchase date (price only, no dividends)"),
        rows=index, cols=date,
        encodings=[("color", series), ("text", series), ("tooltip", b("Value_USD", "Avg"))],
        tooltip_runs=[run(field_tag(series), size=10, color=INK, bold=True, raw=True),
                      run("&#10;", raw=True), run(field_tag(date), size=9, color=INK_2, raw=True)]
        + tip("Growth of 100", index, True) + tip("Value", b("Value_USD", "Avg")),
        label_runs=[run(field_tag(series), size=9, color=INK_2, bold=True, raw=True)],
        table_style=("          <style-rule element='axis'>\n" + axis_title(index, "rows", "Growth of 100")
                     + axis_title(date, "cols", "") + "          </style-rule>\n"
                     "          <style-rule element='gridline'>\n"
                     "            <format attr='line-visibility' scope='cols' value='off' />\n"
                     "          </style-rule>\n"),
        mark_style=("                <format attr='mark-labels-cull' value='true' />\n"
                    "                <format attr='mark-labels-mode' value='line-ends' />\n"
                    "                <format attr='mark-labels-line-first' value='false' />\n"
                    "                <format attr='mark-labels-line-last' value='true' />\n")))

    sheets += [
        text_tile("KPI P Invested", summ, "AMOUNT INVESTED",
                  [big(s("Total_Investment")), NEWLINE, small(s("Number_Of_Holdings")), small(" holdings · "),
                   small(sa("Data_Label"), LOSS, True)],
                  [("text", s("Total_Investment")), ("text", s("Number_Of_Holdings")), ("text", sa("Data_Label"))]),
        text_tile("KPI P Current Value", summ, "CURRENT VALUE",
                  [big(s("Current_Value")), NEWLINE, small("at close on "), small(sa("Valuation_Date"))],
                  [("text", s("Current_Value")), ("text", sa("Valuation_Date"))]),
        text_tile("KPI P Profit Loss", summ, "TOTAL PROFIT / LOSS",
                  [big(s("Total_Profit_Loss"), color=GAIN), NEWLINE,
                   small(s("Portfolio_Return"), GAIN, True), small(" return on money invested")],
                  [("text", s("Total_Profit_Loss")), ("text", s("Portfolio_Return"))]),
        text_tile("KPI P Best", summ, "BEST HOLDING",
                  [big(sa("Best_Asset"), 12), NEWLINE, small(s("Best_Asset_Return"), GAIN, True),
                   small(" return")],
                  [("text", sa("Best_Asset")), ("text", s("Best_Asset_Return"))]),
        text_tile("KPI P Worst", summ, "WEAKEST HOLDING",
                  [big(sa("Worst_Asset"), 12), NEWLINE, small(s("Worst_Asset_Return"), LOSS, True),
                   small(" return")],
                  [("text", sa("Worst_Asset")), ("text", s("Worst_Asset_Return"))]),
        text_tile("KPI P Benchmark", summ, "VS S&P 500",
                  [big(s("Excess_Return_vs_Benchmark"), color=GAIN), NEWLINE, small("portfolio "),
                   small(s("Portfolio_Growth_vs_Start"), INK, True), small(" vs index "),
                   small(s("Benchmark_Growth"), INK, True)],
                  [("text", s("Excess_Return_vs_Benchmark")), ("text", s("Portfolio_Growth_vs_Start")),
                   ("text", s("Benchmark_Growth"))]),
        text_tile("KPI P Concentration", summ, "DIVERSIFICATION (PHASE 5)",
                  [big(sa("Concentration_Level"), 14), NEWLINE,
                   small("HHI of holdings: "), small(s("HHI_Holdings"), INK, True),
                   small("  ·  sectors: "), small(s("HHI_Sectors"), INK, True), NEWLINE,
                   small("Equivalent to "), small(s("Effective_Holdings"), INK, True),
                   small(" equal-sized holdings"), NEWLINE,
                   small("Largest holding: "), small(sa("Largest_Holding"), INK, True), small(" ("),
                   small(s("Largest_Holding_Weight"), INK, True), small(")"), NEWLINE, NEWLINE,
                   run("HHI = sum of squared weights. Below 0.15 = diversified, 0.15–0.25 = moderate, "
                       "above 0.25 = concentrated. 1 ÷ HHI = effective number of holdings.",
                       size=8, color=INK_3)],
                  [("text", sa("Concentration_Level")), ("text", s("HHI_Holdings")),
                   ("text", s("HHI_Sectors")), ("text", s("Effective_Holdings")),
                   ("text", sa("Largest_Holding")), ("text", s("Largest_Holding_Weight"))]),
    ]

    # ------------------------ Risk & Return (Phase 4) ------------------------
    r_ticker, r_company, group = r("Ticker"), r("Company"), r("Risk_Group")
    # Text fields that are only in the tooltip must be wrapped in ATTR().
    r_ticker_attr, r_company_attr = r("Ticker", "Attribute"), r("Company", "Attribute")
    group_attr = r("Risk_Group", "Attribute")
    vol, ann_ret = r("Annualized_Volatility", "Avg"), r("Annualized_Return", "Avg")
    sharpe, mdd = r("Sharpe_Ratio", "Avg"), r("Max_Drawdown", "Avg")
    r_tooltip = ([run(field_tag(r_company_attr), size=10, color=INK, bold=True, raw=True),
                  run(" (", size=10, color=INK_2), run(field_tag(r_ticker_attr), size=10, color=INK_2, raw=True),
                  run(")", size=10, color=INK_2)]
                 + tip("Risk group", group_attr, True) + tip("Annualised return", ann_ret, True)
                 + tip("Annualised volatility", vol, True) + tip("Sharpe ratio", sharpe)
                 + tip("Max drawdown", mdd) + tip("Total return", r("Total_Return", "Avg")))
    r_tip_enc = [("tooltip", r("Total_Return", "Avg")), ("tooltip", sharpe), ("tooltip", mdd),
                 ("tooltip", ann_ret), ("tooltip", vol), ("tooltip", r_company_attr),
                 ("tooltip", r_ticker_attr), ("tooltip", group_attr)]
    sheets.append(Sheet(
        "Risk vs Return", risk, "Circle",
        title_runs=title_runs("Risk vs Return",
                              "Annualised return against annualised volatility · colour = risk group "
                              "(volatility terciles) · grey = S&P 500"),
        rows=ann_ret, cols=vol,
        encodings=[("color", group), ("lod", r_ticker), ("text", r_ticker)] + r_tip_enc,
        tooltip_runs=r_tooltip,
        label_runs=[run(field_tag(r_ticker), size=9, color=INK, bold=True, raw=True)],
        table_style=("          <style-rule element='axis'>\n"
                     + axis_title(ann_ret, "rows", "Annualised return (mean daily return × 252)")
                     + axis_title(vol, "cols", "Annualised volatility (std dev of daily return × √252)")
                     + "          </style-rule>\n"),
        mark_style="                <format attr='size' value='1.6' />\n"))
    for name, measure, title, sub, direction in [
            ("Maximum Drawdown", mdd, "Maximum Drawdown",
             "Largest fall from a previous peak (adjusted close)", "ASC"),
            ("Sharpe Ratio", sharpe, "Sharpe Ratio",
             "(Annualised return − 4% risk-free rate) ÷ volatility · higher = more return per unit of risk",
             "DESC")]:
        sheets.append(Sheet(
            name, risk, "Bar", title_runs=title_runs(title, sub), rows=r_company, cols=measure,
            encodings=[("color", group), ("text", measure)] + r_tip_enc,
            tooltip_runs=r_tooltip,
            label_runs=[run(field_tag(measure), size=9, color=INK, bold=True, raw=True)],
            sort=(r_company, measure, direction),
            table_style=("          <style-rule element='axis'>\n" + axis_title(measure, "cols", title)
                         + "          </style-rule>\n" + no_row_grid(r_company, 190)),
            mark_style="                <format attr='size' value='0.6' />\n"))
    sheets += [
        text_tile("KPI R Most Volatile", summ, "MOST VOLATILE",
                  [big(sa("Most_Volatile"), 12), NEWLINE, small(s("Most_Volatile_Value"), LOSS, True),
                   small(" a year")],
                  [("text", sa("Most_Volatile")), ("text", s("Most_Volatile_Value"))]),
        text_tile("KPI R Least Volatile", summ, "LEAST VOLATILE",
                  [big(sa("Least_Volatile"), 12), NEWLINE, small(s("Least_Volatile_Value"), GAIN, True),
                   small(" a year")],
                  [("text", sa("Least_Volatile")), ("text", s("Least_Volatile_Value"))]),
        text_tile("KPI R Best Sharpe", summ, "BEST RISK-ADJUSTED RETURN",
                  [big(sa("Best_Sharpe"), 12), NEWLINE, small("Sharpe ratio "),
                   small(s("Best_Sharpe_Value"), GAIN, True)],
                  [("text", sa("Best_Sharpe")), ("text", s("Best_Sharpe_Value"))]),
        text_tile("KPI R Drawdown", summ, "DEEPEST DRAWDOWN",
                  [big(sa("Deepest_Drawdown"), 12), NEWLINE, small(s("Deepest_Drawdown_Value"), LOSS, True),
                   small(" from peak")],
                  [("text", sa("Deepest_Drawdown")), ("text", s("Deepest_Drawdown_Value"))]),
        text_tile("KPI R Benchmark", summ, "S&P 500 FOR REFERENCE",
                  [big(s("Benchmark_Volatility")), NEWLINE, small("volatility · max drawdown "),
                   small(s("Benchmark_Max_Drawdown"), LOSS, True)],
                  [("text", s("Benchmark_Volatility")), ("text", s("Benchmark_Max_Drawdown"))]),
    ]

    # -------------------- Goal Simulator (Phases 7-12) ----------------------
    year, g_series = g("Year"), g("Series")
    amount = Field(goal, calc_name("Projection Amount"), "Sum")
    in_period = Field(goal, calc_name("In Investment Period"))
    final_year = Field(goal, calc_name("Is Final Year"))
    sheets.append(Sheet(
        "Portfolio Growth Projection", goal, "Line", uses_params=True,
        title_runs=title_runs("Portfolio Growth Projection",
                              "Year-end value at the expected return vs money put in and the target · ₹"),
        rows=amount, cols=year,
        encodings=[("color", g_series), ("text", g_series)],
        tooltip_runs=[run(field_tag(g_series), size=10, color=INK, bold=True, raw=True)]
        + tip("Year", year) + tip("Amount", amount, True),
        label_runs=[run(field_tag(g_series), size=9, color=INK_2, bold=True, raw=True)],
        filters=[member_filter(in_period, "Yes")],
        table_style=("          <style-rule element='axis'>\n" + axis_title(amount, "rows", "Amount (₹)")
                     + axis_title(year, "cols", "Years from today") + "          </style-rule>\n"),
        mark_style=("                <format attr='mark-labels-cull' value='true' />\n"
                    "                <format attr='mark-labels-mode' value='line-ends' />\n"
                    "                <format attr='mark-labels-line-first' value='false' />\n"
                    "                <format attr='mark-labels-line-last' value='true' />\n")))
    order = g("Series_Order", "Sum")
    sheets.append(Sheet(
        "Goal Progress", goal, "Bar", uses_params=True,
        title_runs=title_runs("Goal Progress", "At the end of the investment period · ₹"),
        rows=g_series, cols=amount,
        encodings=[("color", g_series), ("text", amount)],
        tooltip_runs=[run(field_tag(g_series), size=10, color=INK, bold=True, raw=True)]
        + tip("Amount", amount, True),
        label_runs=[run(field_tag(amount), size=9, color=INK, bold=True, raw=True)],
        filters=[member_filter(final_year, "Yes")],
        sort=(g_series, order, "ASC"),
        table_style=("          <style-rule element='axis'>\n" + axis_title(amount, "cols", "Amount (₹)")
                     + "          </style-rule>\n" + no_row_grid(g_series, 140)),
        mark_style="                <format attr='size' value='0.55' />\n"))
    projected, required = gc("Projected Portfolio Value"), gc("Required Monthly Investment")
    gap, achievement = gc("Goal Gap"), gc("Goal Achievement %")
    contrib, growth = gc("Total Contributions"), gc("Estimated Investment Growth")
    status = Field(goal, calc_name("Goal Status"))
    sheets += [
        text_tile("KPI G Projected", goal, "PROJECTED VALUE",
                  [big(projected), NEWLINE, small("contributions "), small(contrib, INK, True)],
                  [("text", projected), ("text", contrib)], uses_params=True),
        text_tile("KPI G Growth", goal, "ESTIMATED GROWTH",
                  [big(growth, color=GAIN), NEWLINE, small("earned by investment returns")],
                  [("text", growth)], uses_params=True),
        text_tile("KPI G Required", goal, "REQUIRED MONTHLY SIP",
                  [big(required), NEWLINE, small("to reach the target exactly")],
                  [("text", required)], uses_params=True),
        text_tile("KPI G Gap", goal, "GOAL GAP",
                  [big(gap, 15), NEWLINE, small("target − projected value")],
                  [("text", gap)], uses_params=True),
        text_tile("KPI G Achievement", goal, "GOAL ACHIEVEMENT",
                  [big(achievement), NEWLINE, small(status, INK, True)],
                  [("text", achievement), ("text", status)], uses_params=True),
    ]
    return sheets


# ------------------------------ Dashboards ----------------------------------
def kpi_row(z, names, y, h, x0=0, width=DASH_W):
    edges = [x0 + round(i * width / len(names)) for i in range(len(names) + 1)]
    out = []
    for i, name in enumerate(names):
        margins = (12 if i == 0 and x0 == 0 else 6, 12, 12 if i == len(names) - 1 else 6, 6)
        out.append(place(z, (edges[i], y, edges[i + 1] - edges[i], h),
                         f"name='{a(name)}' show-title='false'", margins=margins, padding=4))
    return out


def portfolio_dashboard_xml(name):
    z = Zones()
    zones = [header_zone(z, "Portfolio Performance",
                         "Phases 3, 5 and 6 · SAMPLE / DEMO holdings valued at the latest close (30 Sep 2026) · "
                         "USD · compared with the S&P 500")]
    zones += kpi_row(z, ["KPI P Invested", "KPI P Current Value", "KPI P Profit Loss", "KPI P Best",
                         "KPI P Worst", "KPI P Benchmark"], HEADER_H, 96)
    top = HEADER_H + 96
    rest = DASH_H - top                                # 600
    left_w = 683
    zones.append(place(z, (0, top, left_w, 300), "name='Profit and Loss by Holding'", margins=(12, 6, 6, 6)))
    zones.append(place(z, (0, top + 300, left_w, rest - 300), "name='Sector Exposure'", margins=(12, 6, 6, 12)))
    zones.append(place(z, (left_w, top, DASH_W - left_w, 390), "name='Portfolio vs S&amp;P 500'",
                       margins=(6, 6, 12, 6)))
    zones.append(place(z, (left_w, top + 390, DASH_W - left_w, rest - 390),
                       "name='KPI P Concentration' show-title='false'", margins=(6, 6, 12, 12), padding=12))
    return dashboard_xml(name, zones)


def risk_dashboard_xml(name, risk):
    z = Zones()
    zones = [header_zone(z, "Risk & Return",
                         "Phase 4 (+ optional Phase 13 metrics) · daily adjusted-close returns, 2 Jan 2025 – 30 Sep 2026 · "
                         "252 trading days per year · S&P 500 shown for reference")]
    zones += kpi_row(z, ["KPI R Most Volatile", "KPI R Least Volatile", "KPI R Best Sharpe",
                         "KPI R Drawdown", "KPI R Benchmark"], HEADER_H, 96)
    top = HEADER_H + 96
    rest = DASH_H - top
    left_w = 760
    zones.append(place(z, (0, top, left_w, rest - 64), "name='Risk vs Return'", margins=(12, 6, 6, 6)))
    group = Field(risk, "Risk_Group")
    zones.append(place(z, (0, top + rest - 64, left_w, 64),
                       f"name='Risk vs Return' pane-specification-id='0' param='{a(group.ref)}' type-v2='color'",
                       margins=(12, 0, 6, 12), padding=6))
    zones.append(place(z, (left_w, top, DASH_W - left_w, rest // 2), "name='Sharpe Ratio'",
                       margins=(6, 6, 12, 6)))
    zones.append(place(z, (left_w, top + rest // 2, DASH_W - left_w, rest - rest // 2),
                       "name='Maximum Drawdown'", margins=(6, 6, 12, 12)))
    deps = "\n".join([
        "        <column datatype='string' name='[Risk_Group]' role='dimension' type='nominal' />",
        group.instance_xml("        ")])
    return dashboard_xml(name, zones, risk, deps)


def goal_dashboard_xml(name):
    z = Zones()
    zones = [header_zone(z, "Goal Simulator",
                         "Phases 7–12 · move the sliders: every number and chart recalculates · amounts in ₹ · "
                         "SIP paid at month end, lump sum compounds yearly")]
    side_w = 300
    top = HEADER_H
    zones.append(place(z, (0, top, side_w, 40), "type-v2='text'",
                       [run("YOUR INPUTS", size=9, color=INK_3, bold=True)], margins=(12, 12, 6, 0), padding=8))
    y = top + 40
    for prm in GOAL_PARAMS:
        zones.append(place(z, (0, y, side_w, 74), f"mode='slider' param='{a(prm.ref)}' type-v2='paramctrl'",
                           margins=(12, 0, 6, 0), padding=8))
        y += 74
    zones.append(place(z, (0, y, side_w, DASH_H - y), "type-v2='text'", [
        run("HOW IT WORKS", size=8, color=INK_3, bold=True), NEWLINE,
        run("r = annual return, i = r ÷ 12, n = years, m = 12n", size=8, color=INK_2), NEWLINE,
        run("FV lump sum = P × (1 + r)^n", size=8, color=INK_2), NEWLINE,
        run("FV SIP = PMT × ((1 + i)^m − 1) ÷ i", size=8, color=INK_2), NEWLINE,
        run("Required SIP = (Target − FV lump sum) ÷ SIP factor", size=8, color=INK_2), NEWLINE,
        run("Checked in Python: ₹2,00,000 + 12% for 5 yrs needs ₹7,929/month for ₹10,00,000.",
            size=8, color=INK_3), NEWLINE,
        run("Illustration only, not financial advice; real returns vary.", size=8, color=LOSS),
    ], margins=(12, 0, 6, 12), padding=8))

    x0, w = side_w, DASH_W - side_w
    zones += kpi_row(z, ["KPI G Projected", "KPI G Growth", "KPI G Required", "KPI G Gap",
                         "KPI G Achievement"], top, 96, x0, w)
    y = top + 96
    zones.append(place(z, (x0, y, w, 360), "name='Portfolio Growth Projection'", margins=(6, 6, 12, 6)))
    zones.append(place(z, (x0, y + 360, w, DASH_H - y - 360), "name='Goal Progress'", margins=(6, 6, 12, 12)))
    sources = ("      <datasources>\n        <datasource name='Parameters' />\n      </datasources>\n"
               "      <datasource-dependencies datasource='Parameters'>\n"
               + "\n".join(prm.xml("        ") for prm in PARAMS) + "\n      </datasource-dependencies>\n")
    return dashboard_xml(name, zones, sources_xml=sources)


# ---------------------------------------------------------------------------
# Build the workbook
# ---------------------------------------------------------------------------
def build_twb():
    market_rows = read_csv_rows(MARKET_CSV)
    allocation_rows = read_csv_rows(ALLOCATION_CSV)
    tickers = sorted({row["Ticker"] for row in market_rows})
    dates = sorted({row["Date"] for row in market_rows})
    if not allocation_rows:
        raise ValueError(f"{ALLOCATION_CSV} has no rows.")

    market = build_market_source(tickers)
    alloc = build_allocation_source(tickers)
    hold, summ, sect = build_holdings_source(tickers), build_summary_source(), build_sector_source()
    risk, bench, goal = build_risk_source(), build_benchmark_source(), build_goal_source()
    sheets = build_sheets(market, alloc, dates[0], dates[-1])
    sheets += build_phase3_to_12_sheets(hold, summ, sect, risk, bench, goal)

    main_name = "Market Overview"
    portfolio_name, risk_name, goal_name = "Portfolio Performance", "Risk & Return", "Goal Simulator"
    main_sheets = ["KPI Stocks", "KPI Trading Days", "KPI Best Performer", "KPI Weakest Performer",
                   "KPI Sample Invested", "Stock Price Trend", "Stock Return Comparison",
                   "Portfolio Allocation"]
    portfolio_sheets = ["KPI P Invested", "KPI P Current Value", "KPI P Profit Loss", "KPI P Best",
                        "KPI P Worst", "KPI P Benchmark", "Profit and Loss by Holding", "Sector Exposure",
                        "Portfolio vs S&P 500", "KPI P Concentration"]
    risk_sheets = ["KPI R Most Volatile", "KPI R Least Volatile", "KPI R Best Sharpe", "KPI R Drawdown",
                   "KPI R Benchmark", "Risk vs Return", "Sharpe Ratio", "Maximum Drawdown"]
    goal_sheets = ["KPI G Projected", "KPI G Growth", "KPI G Required", "KPI G Gap", "KPI G Achievement",
                   "Portfolio Growth Projection", "Goal Progress"]

    parts = [
        "<?xml version='1.0' encoding='utf-8' ?>",
        "",
        "<!-- build 20262.26.0819.2015                               -->",
        "<workbook original-version='18.1' source-build='2026.2.2 (20262.26.0819.2015)' "
        "source-platform='win' version='18.1' xmlns:user='http://www.tableausoftware.com/xml/user'>",
        """  <document-format-change-manifest>
    <AccessibleZoneTabOrder />
    <AnimationOnByDefault />
    <AutoCreateAndUpdateDSDPhoneLayouts />
    <MarkAnimation />
    <ObjectModelEncapsulateLegacy />
    <ObjectModelTableType />
    <SchemaViewerObjectModel />
    <SetMembershipControl />
    <SheetIdentifierTracking />
    <SortTagCleanup />
    <WindowsPersistSimpleIdentifiers />
  </document-format-change-manifest>
  <preferences>
    <preference name='ui.encoding.shelf.height' value='24' />
    <preference name='ui.shelf.height' value='26' />
  </preferences>""",
        "  <datasources>",
        parameters_datasource_xml(),
        "\n".join(datasource_xml(ds) for ds in (market, alloc, hold, summ, sect, risk, bench, goal)),
        "  </datasources>",
        actions_xml([main_name, portfolio_name, risk_name]),
        "  <worksheets>",
        "\n".join(worksheet_xml(s) for s in sheets),
        "  </worksheets>",
        "  <dashboards>",
        main_dashboard_xml(market, main_name),
        portfolio_dashboard_xml(portfolio_name),
        risk_dashboard_xml(risk_name, risk),
        goal_dashboard_xml(goal_name),
        "  </dashboards>",
        windows_xml([(main_name, main_sheets), (portfolio_name, portfolio_sheets),
                     (risk_name, risk_sheets), (goal_name, goal_sheets)], sheets, main_name),
        "</workbook>",
        "",
    ]
    return "\n".join(parts)


def write_extracts(target_dir):
    """
    Write one Tableau extract (.hyper) per CSV, table "Extract"."Extract",
    using Tableau's Hyper API. Column types follow the workbook's data source
    definitions. Returns {csv name: path of the .hyper file}.
    """
    from tableauhyperapi import (Connection, CreateMode, HyperProcess, Nullability, SqlType,
                                 TableDefinition, TableName, Telemetry, escape_string_literal)

    sql_type = {"string": SqlType.text(), "date": SqlType.date(), "real": SqlType.double(),
                "integer": SqlType.big_int()}
    tickers = sorted({row["Ticker"] for row in read_csv_rows(MARKET_CSV)})
    sources = [build_market_source(tickers), build_allocation_source(tickers),
               build_holdings_source(tickers), build_summary_source(), build_sector_source(),
               build_risk_source(), build_benchmark_source(), build_goal_source()]
    target_dir.mkdir(parents=True, exist_ok=True)
    out = {}
    with HyperProcess(telemetry=Telemetry.DO_NOT_SEND_USAGE_DATA_TO_TABLEAU) as hyper:
        for ds in sources:
            path = target_dir / extract_name(ds.filename)
            table = TableDefinition(TableName("Extract", "Extract"), [
                TableDefinition.Column(c.name, sql_type[c.datatype], Nullability.NULLABLE)
                for c in ds.columns])
            with Connection(hyper.endpoint, str(path), CreateMode.CREATE_AND_REPLACE) as conn:
                conn.catalog.create_schema("Extract")
                conn.catalog.create_table(table)
                csv_path = escape_string_literal(str(TABLEAU_DATA_DIR / ds.filename))
                rows = conn.execute_command(
                    f"COPY {table.table_name} FROM {csv_path} WITH (FORMAT csv, HEADER, NULL '')")
            out[ds.filename] = path
            print(f"  Extract: {path.name} ({rows:,} rows)")
    return out


def main():
    import sys
    import tempfile

    global USE_EXTRACTS
    USE_EXTRACTS = "--live" not in sys.argv
    twb = build_twb()
    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp, \
            zipfile.ZipFile(OUTPUT_FILE, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(TWB_NAME, twb.encode("utf-8"))
        if USE_EXTRACTS:
            for csv_name, path in write_extracts(Path(tmp)).items():
                archive.write(path, f"Data/Extracts/{extract_name(csv_name)}")
        else:
            for csv_name in ALL_CSVS:
                archive.write(TABLEAU_DATA_DIR / csv_name, f"Data/tableau/{csv_name}")
    kind = "extracts" if USE_EXTRACTS else "live CSV connections"
    print(f"Saved: {OUTPUT_FILE.relative_to(PROJECT_ROOT)} ({kind})")


if __name__ == "__main__":
    main()
