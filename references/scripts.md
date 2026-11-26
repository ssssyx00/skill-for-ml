# 课件索引与学习记录脚本

仅在首次使用脚本或需要查参数时读取。脚本本地运行，不上传课件、不联网、不发布学习日志。

## 环境与输出位置

需要 Python 3.9+。PDF 提取/渲染依赖 PyMuPDF；PPTX 提取与进度保存仅使用 Python 标准库。先尝试现有依赖，缺失时在允许的环境安装 `python -m pip install -r requirements.txt`，或使用宿主已有 PDF 工具，不虚构脚本成功。

以下命令从 skill 目录执行；`/your/course` 是应替换的学习目录。索引属于可重建中间数据；学习记录须保存在宿主要求的持久化位置。ChatGPT 等宿主若要求额外保存步骤，写本地 JSON 后还要完成该步骤，才能承诺跨会话可用。不要把实际课件、索引或个人学习记录放进公开 skill 仓库。

## 课件索引

```bash
python scripts/index_courseware.py /your/course/12-Decision-Tree.pdf --out /your/course/index-run1
python scripts/index_courseware.py /your/course/12-Decision-Tree.pdf --pages 21-28,43 --render all --out /your/course/index-entropy
python scripts/index_courseware.py /your/course/lecture.pptx --out /your/course/index-pptx
```

可以一次传入多个文件。输出子目录为“文件名 + 文件内容哈希”，包括 `index.json`、逐页 `pages.txt`，以及指定渲染时的 `pages/pNNNN.png`。

- `page_count` 是源文件总页数，`indexed_page_count` 是本次实际提取数。`page` 始终是原文件中从 1 开始的真实页序，局部提取不从 1 重新编号。
- `printed_page` 默认空，不能凭 PDF 页序推测课件印刷编号。引用直接使用 `locator`；需要印刷编号时查看原页核实。
- 所有原文保留，包括重复文字、公式文本和数字，不把频繁出现的内容自动当成页眉删除。
- `duplicate_candidates` 仅表示完整提取文字和备注在空白规范化后相同，不表示图像相同。需要看两张原页，确认没有新增公式、箭头或图例后，才在讲解中合并；脚本不删任何页。
- `--render needed` 根据稀疏文本、图片或矢量图提示渲染；该检测不是数学识别。公式不完整或符号可疑时改用相关页的 `--render all`。不提供 OCR 或保证数学转写准确。
- PPTX 按演示文稿的真实顺序读取，不按 slide 文件名猜顺序；通过关系链接读取备注，不猜 notesSlide 编号。图、动画、数学排版须看原稿或导出 PDF；PPTX 的 `--render` 不生成图片，索引明确标记需要视觉核对。
- 相同输出子目录已存在时拒绝覆盖。先复用现有完整索引；需要换范围或渲染方式时选新的输出目录。核对 `source_sha256`，原文件变更后重新提取。
- 任一文件失败时返回非零退出码，并列明成功文件与错误；部分输出标为 `INCOMPLETE.txt`，不可当成整讲已经读取。不会改写输入文件。

## 学习记录

```bash
python scripts/study_state.py --file /your/course/progress.json record information-gain --source '12-Decision-Tree.pdf | PDF page 21-28' --coverage covered --next '从决策树分裂例题继续'
python scripts/study_state.py --file /your/course/progress.json record information-gain --evidence self-reported --evidence-note '用户说理解了；尚未独立做题'
python scripts/study_state.py --file /your/course/progress.json park em-jensen --topic em --source '18-Clustering2 (1).pdf | PDF page 83-86' --gap 'Jensen取等条件' --understood '能解释E步软分配、M步更新' --reason '非阻断的证明细节，本轮先学PCA' --return-when '第二轮复习EM时'
python scripts/study_state.py --file /your/course/progress.json show
python scripts/study_state.py --file /your/course/progress.json resolve em-jensen --evidence-note '填写实际解决卡点的依据'
```

上述教学状态是调用格式示例，不代表真实用户已经理解；来源页码也须在当前材料中核对后使用。

`record` 仅更新提供的字段，其他状态保留。`coverage` 可为 `uncovered/covered`；`evidence` 可为 `unverified/self-reported/explained-back/basic-problem-passed`。默认未验证；标为其他证据等级必须提供实际依据。脚本只校验字段，无法验证用户是否真会做，助手必须如实填写。

`park` 保存具体卡点、已经理解的内容、暂缓理由与返回条件；`resolve` 显式关闭卡点，保留历史。`show` 读取记录，不创建虚假的空进度。写入采用锁和原子替换，保留变更历史，损坏的 JSON 不会被空记录覆盖。遇到锁冲突先确认是否有写入正在进行；不要盲目删除锁。

## 审查过的上游实现与取舍

- [lecture-notes-tutor / extract_pptx.py](https://github.com/YUANYINGLONG-91/lecture-notes-tutor/blob/main/scripts/extract_pptx.py)：参考逐页文字和备注关系读取；本实现另按 presentation 中的顺序取页，避免文件序号与展示顺序不同。
- [study-atlas / extract.py](https://github.com/phanthanhdieulinh/study-atlas/blob/main/skills/study-atlas/scripts/extract.py)：参考逐页索引、原页渲染和图文核对；不采用自动删除高频文字、遍历每个数字生成记忆材料等做法。
- [claude-study-skills / tutor](https://github.com/adityakumar68/claude-study-skills/blob/main/tutor/SKILL.md)：参考学习状态和误解记录流程；这里独立实现单一 JSON 记录与历史，不采用每轮强制提问、掌握门槛或长期复习排程。

上述脚本为独立实现，不复制上游脚本代码，无需安装这些项目。自检命令：`python -m unittest discover -s tests -v`。
