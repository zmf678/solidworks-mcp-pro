# SolidWorks MCP 建模指南（中文）

本文件是 `solidworks://guide-zh` 资源，面向中文用户和中文 Agent。英文完整版是
`solidworks://guide` / `guide.md`。

## 1. 坐标、单位与标准

- 所有长度 **mm**，角度 **度**；服务在 COM 边界转换为米/弧度。
- 默认建模与制图标准为 **GB**；ISO 是显式回退（Hole Wizard 用
  `standard="ISO"`）。
- 新几何从 **Front 平面（XY）** 开始，沿 **+Z** 拉伸，z = 0 起：
  - `add_box` 范围 x 0..width、y 0..height、z 0..depth。
  - `add_disc` 以原点为中心；`add_cylinder`、`add_revolved_profile` 绕 **Y**
    轴旋转。`add_revolved_profile` 可用 `axis_mm` 指定 Front 平面上的任意轴。
  - 扫掠路径在 Front 平面；`add_swept_profile` 的路径必须从原点朝 **+X** 开始，
    截面画在 Right 平面（u 沿 -Z，v 沿 +Y）。
- 面用朝向选择：`+x`、`-z`……`*_on_face` 工具接收面上的 3D 点，选择该方向上
  **过该点** 的平面；`+z:outer` / `+z:inner` 强制最外/最内面。
- 零件必须是 **Y-up** 模板；Z-up 模板会被拒绝。

## 2. 小步建模、每一步验证

- 每个建模调用返回实测体积、质量、包围盒。**每一步都用手算对照**，第一个不匹配
  就停下来修。
- 常用手算：
  - 棱柱：底面积 × 深度；
  - 旋转体：面积 × 2π × 形心半径（Pappus）；
  - 扫掠：截面面积 × 路径长度；
  - 螺纹槽：面积 × 2π × 形心半径 / 螺距 × 长度。
- 选择前先看：`list_faces` / `list_edges` 给索引、法向、面积、轴线；
  `screenshot` 可看任意方向，`zoom_mm` 放大细节。
- 做错了用 `delete_feature(name)` 撤销；它会连同草图删除，有依赖时会拒绝并列出。
- 工具返回 `{ok: false, error}` 表示拒绝或 SolidWorks 失败；错误会说明原因，零件
  保持调用前状态。

## 3. 尺寸与草图

- 每个工具都让草图 **完全定义**：只在输入恰好水平、垂直或过原点时加关系，其余
  从原点标一个尺寸。任何拖动都不会改变几何。
- 工具返回 `dimensions`（`{角色: 尺寸名}`）和 `fully_defined: true`。用
  `set_dimension(name, value)` 改尺寸，rebuild 后体积会变化。
- 常见角色：box `width`/`height`/`depth`；disc `diameter`/`thickness`；
  cylinder `radius`/`height`；孔 `diameter`/`x`/`y`；槽 `end1_x`/`end1_y`/
  `end2_x`/`end2_y`/`width`。
- 超过 24 点的轮廓、扫掠路径和样条会改为“固定”，不再逐点标尺寸；要改就重建。
- 用方程联动：`set_equation('"W" = 40')`，再
  `set_equation('"width@Sketch1" = "W"')`。孔位也可绑到宽度：
  `set_equation('"x@Sketch2" = "width@Sketch1" / 2')`。

## 4. 常用配方

- **孔**：`add_hole`（+Z 通孔）、`add_counterbore_hole`（+Z 沉孔）、
  `add_hole_on_face`（任意平面，通孔或盲孔）。
- **标准孔（GB 默认）**：`add_hole_wizard`：
  - `kind="clearance"`：GB/T 5277；M3 为 3.2 / 3.4 / 3.6（close / normal / loose）。
  - `kind="counterbore"`：GB/T 70.1 内六角圆柱头螺钉。
  - `kind="countersink"`：GB/T 70.3 内六角沉头螺钉。
  - `kind="tapped"`：GB 螺纹底孔 + 修饰螺纹；`thread="modeled"` 切真实可打印
    螺纹（GB/T 196 基本小径）。
  - 供应商要求 ISO 时传 `standard="ISO"`。
- **螺纹**：`add_thread("M10x1.5", ...)`；外螺纹杆径必须是公称直径，内螺纹先钻
  GB/T 196 基本小径 D - 1.0825P（M10x1.5 → 8.376 mm）。
- **凸台/垫**：`add_boss_on_face`、`add_extruded_profile_on_face`。
- **型腔/槽**：`cut_profile`、`cut_profile_on_face`、`cut_offset_pocket`、
  `cut_slot`、`add_extruded_slot`、`cut_profile_through_plane`。
- **圆角/倒角/抽壳**：`add_fillet`、`add_full_round`、`add_chamfer`、
  `add_shell`。圆角失败时会列出放不下的边和能放下的最大半径。
- **阵列/镜像**：`add_linear_pattern`、`add_circular_pattern`、`add_mirror`。
  镜像面必须在材料内：box 范围 x 0..w，所以关于 `offset_mm = w/2` 镜像。
- **文字**：`add_text_on_face` 可刻字或凸字；字体必须已安装，顶面和前面读起来
  最自然。
- **图纸**：`make_drawing("part.pdf", template=...)` 生成第一角三视图 + 等轴测，
  A4；传 GB `gb.drwdot` 获得 GB 标题栏。零件必须先保存。
- **装配**：`insert_component` 按原点放置；`add_mate` 支持 coincident、distance、
  parallel、perpendicular、angle、concentric；配合后会测量回读，坏配合会删除并
  恢复组件。`check_interference` 检查真实重叠，贴合面不算。
- **运动**：`check_motion(dimension, values, distances)` 逐步检查关节范围；
  `swept_region` 给出运动件在平面上的包络，供 `add_sketch` 使用。

## 5. 3D 打印

- 滑动配合留 0.2–0.4 mm 间隙，ASA/ABS 比 PLA 更大；关键接口先打小样。
- 打印孔会缩小 0.1–0.2 mm；穿过零件的孔要按最宽截面（如扁舌的对角线）留量。
- 热熔螺母按厂家孔径；常见 M3×5.7 用约 4.0 mm，深度至少多 0.5 mm。
- 文字至少 5 mm 高，笔画宽于喷嘴（0.4 mm）；刻字 0.4–0.6 mm，凸字约 1 mm。
- 打印前用 `check_printability(up="+z", overhang_deg=45, min_wall_mm=0.8)` 检查
  悬垂、孤岛、薄壁和床面接触；试不同 `up` 找最佳方向。
- 导出用 `export(..., quality="fine")`，STL/3MF 保留模型坐标。

## 6. 限制与注意事项

- 不支持：网格直接导入为实体（先用 `slice_mesh` 剖切）、任意平面草图（人工基准面
  可用于镜像/贯穿切除）、多边形轮廓内的自由圆弧（用圆角、旋转、样条、槽或孔）。
- 连续多边形切割的共享壁必须用完全相同的点；几微米偏差会留下薄片面，下一次切割
  失败。
- SolidWorks 长时间会话内存会增长；低内存提示时保存并重启 SolidWorks，不要在
  运行中重启（COM 连接会断）。
- 只验证 SOLIDWORKS 2026；其他版本先跑
  `uv run solidworks-mcp --selftest`。

## 7. GB 标准说明

GB 默认不等于 GB 认证。标题栏、公差、配合、粗糙度和几何公差仍需人工审核。完整
标准依据和实现矩阵见 `Docs/zh-CN/MODELING-STANDARDS.md`。
