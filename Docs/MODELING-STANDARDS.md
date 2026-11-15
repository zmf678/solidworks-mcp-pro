# Modelling standard: GB

The default modelling and drawing standard for this fork is **GB** (中华人民共和国国家标准).
ISO remains available as an explicit fallback where a GB table is not implemented
or where a supplier requires ISO.

This document states the intended standard, what the code actually implements,
and what still requires a human check. It is not a certificate of GB compliance.

## 1. Normative basis

| Area | GB standard |
|---|---|
| 3D modelling, general | GB/T 26099.1-2010 机械产品三维建模通用规则 第1部分：通用要求 |
| 3D modelling, parts | GB/T 26099.2-2010 机械产品三维建模通用规则 第2部分：零件建模 |
| 3D modelling, assemblies | GB/T 26099.3-2010 机械产品三维建模通用规则 第3部分：装配建模 |
| Sheet sizes | GB/T 14689-2008 技术制图 图纸幅面和格式 |
| Scale | GB/T 14690-1993 技术制图 比例 |
| Lettering | GB/T 14691-1993 技术制图 字体 |
| Projection | GB/T 14692-2008 技术制图 投影法（第一角法） |
| Views | GB/T 17451-1998 技术制图 图样画法 视图；GB/T 4458.1-2002 机械制图 图样画法 视图 |
| Dimensions | GB/T 4458.4-2003 机械制图 尺寸注法 |
| Tolerances and fits on drawings | GB/T 4458.5-2003 机械制图 尺寸公差与配合注法 |
| Sections | GB/T 4458.6-2002 机械制图 剖视图和断面图 |
| Title block | GB/T 10609.1-2008 技术制图 标题栏 |
| Parts list | GB/T 10609.2-2009 技术制图 明细栏 |
| Limits and fits | GB/T 1800.1-2020；GB/T 1801-2009 |
| Surface texture | GB/T 1031-2009 |
| Geometric tolerancing | GB/T 1182-2018；GB/T 1184-1996 |
| Metric threads | GB/T 192-2003；GB/T 196-2003；GB/T 197-2003 |
| Clearance holes | GB/T 5277-1985 紧固件 螺栓和螺钉通孔 |
| Socket head cap screws | GB/T 70.1-2008 内六角圆柱头螺钉 |
| Countersunk socket head screws | GB/T 70.3-2008 内六角沉头螺钉 |
| STEP / product data | GB/T 16656 系列（对应 ISO 10303） |
| Additive manufacturing terms | GB/T 35351-2017 增材制造 术语 |

Always verify that a cited edition is still current for the project and the
customer's contract. Standard numbers are identifiers, not a substitute for the
actual tables.

## 2. Implementation matrix

| Requirement | Status in this fork | Where |
|---|---|---|
| Millimetres and degrees at the tool boundary | Implemented | `units.py`; every `*_mm` / `*_deg` tool argument |
| Fully defined sketches, dimensions from the origin | Implemented; every part test asserts it | `session/sketching.py`, `tests/conftest.py` |
| GB Hole Wizard tables | **Default** (`standard="GB"`); ISO fallback | `session/holes.py`, `constants.py` |
| GB/T 5277 clearance holes | Implemented through SolidWorks GB table | `add_hole_wizard(kind="clearance")` |
| GB/T 70.1 counterbore | Implemented through SolidWorks GB table | `add_hole_wizard(kind="counterbore")` |
| GB/T 70.3 countersink | Implemented through SolidWorks GB table | `add_hole_wizard(kind="countersink")` |
| GB tapped holes | Implemented through SolidWorks GB table | `add_hole_wizard(kind="tapped")` |
| GB/T 196/197 metric threads | Implemented with SolidWorks' metric thread profiles | `add_thread` |
| GB/T 14692 first-angle drawing views | Implemented | `make_drawing` |
| GB/T 14689 A4 sheet | Implemented | `make_drawing` |
| GB title block | Depends on the drawing template; pass a GB `.drwdot` | `make_drawing(template=...)` |
| GB/T 10609.2 parts list / BOM | Not automated | manual / future work |
| GB/T 4458.5 tolerance and fit annotations | Not automated | manual / future work |
| GB/T 1031 surface texture annotations | Not automated | manual / future work |
| GB/T 1182 geometric tolerances | Not automated | manual / future work |
| GB/T 26099 model-quality checks | Partially: fully defined sketches, named features, history order | `list_features`, `read_sketch`, tests |
| STEP exchange | Supported as a file format; not a GB certification | `export("*.step")` |

## 3. How to use the GB default

```python
# GB is the default; the result's hole["standard"] is "GB".
hole = add_hole_wizard("clearance", "M3", "+z", 20, 10, 10)

# Explicit ISO fallback for a supplier that requires ISO.
hole = add_hole_wizard("clearance", "M3", "+z", 20, 10, 10, standard="ISO")

# GB drawing with a GB title block.
make_drawing("bracket.pdf", template=r"C:\...\gb.drwdot")
```

SolidWorks ships GB drawing templates such as `gb.drwdot` and GB sheet formats
such as `a4 - gb portrait.slddrt`. The path differs by installation and language;
pass the template explicitly rather than hard-coding an install path.

## 4. What "GB default" does not mean

- It does **not** mean the generated drawing is a fully GB-compliant production
  drawing. Title block, tolerances, fits, surface texture and geometric
  tolerances still need a human check.
- It does **not** change SolidWorks' internal thread profile library. The metric
  thread basic profile is shared between GB/T 192/196/197 and ISO 68/724; the
  designation (`M10x1.5`) is the same.
- It does **not** make the model a certified GB/T 26099 model. The project
  implements the controllable parts (units, fully defined sketches, feature
  naming, history order, verification) and documents the rest.
- It does **not** change the Y-up part-template requirement. Y-up is the
  SolidWorks modelling frame used by the tools; it is independent of the drawing
  projection standard.

## 5. Change policy

- GB is the default for `add_hole_wizard`. Changing that default is a breaking
  change and requires a major/minor-release note.
- ISO remains a supported explicit fallback; do not remove it without a
  deprecation cycle.
- Any new standard-table feature must state its GB standard number, its ISO
  equivalent (if any), and whether it is automatic or manual.
- When a GB and ISO value differ, the GB table wins for the default path.
