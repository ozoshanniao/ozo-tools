# Rotation Follow 使用说明（OZO_Tools 0.10.1）

入口：3D View → Sidebar → OZO_Tools → RIG Tools → Rotation Follow。

本工具仅连接 Copy Rotation，不包含 Copy Transforms、IK/FK、缩放隔离或动画烘焙。适用于当前活动的本地、可编辑、单用户骨架，支持编辑和姿态模式。

## 1. 固定本次操作范围

1. 在 Rotation Source 明确选择同一骨架上的来源骨。
2. 选中所有受影响骨，点击 Load Selected。
3. Affected Bones 显示本次固定列表。链序号格式为“第几条链.链内第几根”。

后续选择发生变化不会改变这个列表，包括 Create MCH 后选中了机制骨。换一批受影响骨时，明确再次点击 Load Selected。若同时选中了一个控制骨和它对应的已记录 MCH，将报告范围重叠。

Load Selected 会保存稳定骨骼身份并生成一份新的影响值预览，但不增加约束或改层级。来源骨不能位于受影响列表内。

## 2. Direct Constraint

选择 Direct Constraint，设置选项后点击 Connect Rotation。

每根受影响骨收到一个带唯一标记的 OZO Rotation Follow Copy Rotation，目标为 Rotation Source。同一骨骼若有 Stretch To，新约束放在第一个 Stretch To 前；否则放在末尾。其他约束相对顺序保留。

此模式不增加骨骼，不改父级、静止位置、长度、朝向、Deform 或集合。已有用户 Copy Rotation / Copy Transforms / IK 机制发生冲突时会指出骨骼与约束，不覆盖。

## 3. MCH Parent：保留手动调整阶段

1. 选择 MCH Parent，设定 MCH Length（默认 0.3，骨架空间单位，界面遵循场景显示单位）。
2. Specify Collection 开启后选择已有集合，包括嵌套集合；关闭时使用当前活动集合。
3. 点击 Create MCH，只创建原父级 → MCH_ROT_控制器名 → 原控制器，不增加跟随约束。
4. 在编辑模式调整 MCH 朝向、Roll 或长度。可以保存文件、重新打开、重载插件后再继续。
5. 点击 Connect Rotation，将约束放在各自的 MCH 上。控制骨通过父子关系继承跟随，仍可独立旋转。

MCH 默认保持受控骨静止朝向；头部位于受控骨静止头部，Deform 关闭，不复制动画、约束、驱动器或用户自定义属性。原控制器不改名，静止几何保留。原父级及 Connected 状态被记录；插入层级使用 Keep Offset，避免因 MCH 长度不同而移动控制骨。原来无父级的 MCH 保持无父级。

命名示例：Finger_03.L → MCH_ROT_Finger_03.L；Finger_03.001.R → MCH_ROT_Finger_03.R。保留有意义的编号及末尾侧别。名称冲突会在创建前报告。

已完成机制重复 Create MCH 会跳过，普通 Connect 更新不会新增骨骼或重置手调的 MCH。现有绑定切换 Direct/MCH 仍会被拒绝；本版没有跨模式结构转换或通用移除工具。

### 调整长度：不需要删除 MCH

修改 MCH Length 后，点击 Create MCH 下方的 **Update Length**。它只改变受影响列表中现有 MCH 的长度，保留头部、方向、Roll、控制骨静止几何、约束、驱动器及集合。骨骼改名后仍按身份识别。操作支持 Undo/Redo。

如果 MCH 有用户新增的 Connected 子骨，改变长度可能移动该子骨，工具会报告冲突并停止本批修改。

### 已经手动删除 MCH：显式恢复

1. 确认 Affected Bones 列表中是需要恢复的原控制骨；必要时选中它们并重新 Load Selected。
2. 设置新的 MCH Length、集合。
3. 点击 **Recreate Missing**。已有 MCH 跳过，仅恢复记录中缺失的 MCH，重新插入原父级 → MCH → 控制骨。
4. 检查朝向和长度，再点击 Connect Rotation。

恢复阶段不自动重连旋转。旧的总属性映射保留，重新 Connect Rotation 后恢复驱动，不改写或删除共享属性。删除前手调的 MCH 朝向无法从已删除骨骼取回，因此恢复时采用原控制骨静止朝向；需要时重新手调。

恢复要求控制骨静止几何未变、仍挂在记录的原父级下、记录中的来源和属性骨仍存在。存在同名替代骨、孤立动画或非预期层级时会指出具体冲突，不自动认领替代骨或清除用户数据。中间状态可以保存重开；恢复失败会回滚本次创建和记录修改，并支持 Undo/Redo。

## 4. 影响值及衰减

Auto Falloff 默认关闭：每根基础值均为 1，也允许处理互不成链的独立骨骼。

开启后显示 Start Influence、End Influence（默认 0.2 / 0.8）：

- 三根连续骨链默认得到 0.2、0.5、0.8。
- 交换 Start/End 得到反向分布。
- 多条独立连续链各自从 Start 到 End；单骨使用 Start。
- 沿真实父子关系排序，以骨骼索引等距计算，不参考名称、选择先后或物理长度。
- 内部漏选、分叉或重叠会明确报错，请分批选择。

只有 Load Selected 或 Apply Falloff 重新计算分布。修改端点数值不会不断覆盖逐骨微调。列表里的基础值可直接编辑，再点击 Connect Rotation 更新实际约束。

关闭 Auto Falloff 会把列表预览重置为 1；下一次明确连接/属性更新采用 1，不继续使用隐藏的旧系数。

## 5. 约束选项

Constraint Options 默认折叠。默认 Target Space=Local、Owner Space=Local、Mix=Replace、XYZ 全部开启、不反向。

可设置本版 Blender 原生 Copy Rotation 的混合模式、基础空间、各轴开关与各轴反向。Custom 没有开放，避免出现缺少必要参考物体/骨骼字段的选项。

改面板设置先预览；点击 Connect Rotation 才写入约束。不会自动改变原控制器旋转模式、清除姿态、动画、驱动器或原约束。

## 6. 可选总跟随属性

普通 Influence 工作流无需属性和驱动器。需要总控时：

1. 先完成 Connect Rotation。
2. 开启 Connect Follow Property。
3. Property Bone 明确选择属性承载骨。
4. 选择 New Property 并输入名称，或 Existing Property 选择已有数值属性。
5. 点击 Connect Property，建立“总属性 × 列表基础值”的驱动关系。

新属性为浮点，范围 0～1，当前值及默认值为 1。已有属性须为有限数值标量，当前值在 0～1；原值、范围、关键帧不改写。新建模式遇到已存在名称会提示改用 Existing Property，已有同一连接的重复点击除外。

例如基础值 0.2/0.5/0.8，总属性 0.5 时，实际影响为 0.1/0.25/0.4。Direct 驱动控制骨约束，MCH 模式驱动机制骨约束。左右是否共享完全由用户明确选择的属性决定。

逐骨基础值变化后点击 Connect Rotation 更新，工具会同步驱动表达式，无需手工编辑。Connect Property 同样采用本次预览系数，但不会顺便应用尚未连接的空间/轴向等选项。关闭 Auto Falloff 后，驱动关系变为总属性 × 1。

Disconnect Property 只移除验证通过的本工具驱动，并恢复当前预览基础值，保留共享属性。隐藏属性设置区不会自动解除已经建立的连接。

## 7. 持久性、冲突与范围边界

机制记录保存在骨架数据上，身份与旧 Tweak/Socket 的记录互不覆盖。来源、受控骨、MCH、属性骨骼改名后仍可识别；删除后用同名新骨替换会被视为缺失原身份，不会误认成旧骨。

复制原骨来做新控制器后若出现重复编号提示，使用 RIG Tools → Bone Identity → Repair Duplicate IDs，一次检查公共编号和旧 Tweak/FK 编号。通常无需选择副本或指定原骨；无法区分时在 Manual / Advanced 中指定 Original Bone。再回到 Rotation Follow 重新 Load Selected。详见 [一键修复重复编号](BONE_IDENTITY_zh.md)。

MCH 朝向和长度手动修改允许；控制器静止几何、记录的层级、缺失来源等非预期变化会停止连接并指出问题。

0.10.3 修正了导入骨骼矩阵在编辑模式切换后产生微小标准化舍入差时的误报。检查分别比较头部位置、实际长度和标准化方向；位置/长度及方向向量阈值仍为 0.00001，仅对接近刚性的矩阵基轴长度误差（最多 0.00005）做标准化。真实移动、改长、转向，以及明显缩放、剪切、反射或损坏矩阵仍会停止连接。

如果清除身份时提示某骨骼已有机制身份，应保留该原骨标记；该入口面向新复制的控制器，不是消除几何检查报错的重置按钮。

Blender 约束不支持自定义身份属性。本工具通过持久记录、骨骼/来源身份、唯一名称标记、实际设置与驱动签名联合校验所有权。用户改名或改动了受管约束/驱动时会报冲突，不自动认领或覆盖。重新打开文件后，人为复制一份所有记录特征完全一致的约束，与原约束无法进一步区分。

循环检查覆盖明显的同骨架父子、约束目标、变换通道驱动依赖，不宣称证明任意跨骨架或脚本驱动图安全。

本工具保持 Blender 原生 Copy Rotation 求值。影响值不是在所有旋转组合中都等于逐轴欧拉角乘法；非均匀对象缩放、不同静止轴、空间转换可能引入剪切或轴耦合。已用适度旋转、不同骨轴、手调 MCH 及带旋转/非均匀缩放对象与独立原生约束对照验证；不做剪切补偿或任意姿态匹配。零缩放等奇异/非有限世界变换拒绝处理。

每个操作先完成本批预检。失败会恢复本次部分修改，支持 Blender Undo/Redo，并恢复原活动对象、选择和编辑/姿态模式。Details 弹窗及控制台提供数量和具体条目。

工具不自动保存 blend，不自动烘焙或补偿已有动画。保持静止几何不代表已有动画求值完全不变。
