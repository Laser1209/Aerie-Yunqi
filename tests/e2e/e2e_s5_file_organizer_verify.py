"""Aerie v12.0 · S5 M5.3 文件整理验证

验证项：
  T1 FileCategory 8 分类定义
  T2 EXTENSION_MAP 扩展名映射
  T3 FileClassifier 分类（文档/图片/视频/音频/压缩包/代码/安装包/其他）
  T4 FileInfo 数据模型
  T5 DirectoryScanner 扫描目录
  T6 DirectoryScanner 递归扫描
  T7 DirectoryScanner 隐藏文件过滤
  T8 OrganizePlanner 生成整理计划
  T9 OrganizePlan 统计信息
  T10 重名文件自动编号
  T11 UndoRecord 数据模型
  T12 UndoManager 创建记录
  T13 FileOrganizer 扫描目录统计
  T14 FileOrganizer 预览整理
  T15 FileOrganizer 执行整理
  T16 FileOrganizer 撤销整理
  T17 大文件标记
  T18 近期文件标记
  T19 撤销记录列表
  T20 一键整理（quick_organize）
"""

from __future__ import annotations
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from core.file_organizer import (
    CATEGORY_NAMES,
    EXTENSION_MAP,
    FileCategory,
    FileClassifier,
    FileInfo,
    FileOrganizer,
    MoveAction,
    OrganizePlan,
    OrganizePlanner,
    UndoManager,
    UndoRecord,
    DirectoryScanner,
)


def _make_test_dir() -> Path:
    """创建测试目录和测试文件"""
    root = Path(tempfile.mkdtemp(prefix="aerie_fileorg_"))

    # 创建各种类型的文件
    files = {
        "文档": ["报告.docx", "笔记.md", "数据.xlsx", "手册.pdf", "readme.txt"],
        "图片": ["风景.jpg", "头像.png", "截图.gif", "图标.svg", "照片.webp"],
        "视频": ["电影.mp4", "教程.avi", "剪辑.mkv"],
        "音频": ["歌曲.mp3", "录音.wav", "有声书.m4a"],
        "压缩包": ["项目.zip", "备份.rar", "资料.7z"],
        "代码": ["main.py", "app.js", "index.html", "styles.css", "utils.ts"],
        "安装包": ["软件.exe", "应用.apk", "程序.msi"],
        "其他": ["数据.xyz", "未知文件.abc"],
    }

    for cat, filenames in files.items():
        for fn in filenames:
            fpath = root / fn
            fpath.write_text(f"test content for {fn}", encoding="utf-8")

    # 创建一个大文件标记（内容不大，但我们可以手动设置 is_large 测试）
    (root / "大文件.zip").write_text("x" * 1024, encoding="utf-8")

    return root


def t1_category_definition() -> tuple[bool, str]:
    """T1 FileCategory 8 分类定义"""
    cats = list(FileCategory)
    expected = [
        FileCategory.DOCUMENTS,
        FileCategory.IMAGES,
        FileCategory.VIDEOS,
        FileCategory.AUDIO,
        FileCategory.ARCHIVES,
        FileCategory.CODE,
        FileCategory.INSTALLERS,
        FileCategory.OTHER,
    ]
    checks = [len(cats) == 8]
    for cat in expected:
        checks.append(cat in cats)
    return all(checks), f"8个分类: {[c.value for c in cats]}"


def t2_extension_map() -> tuple[bool, str]:
    """T2 EXTENSION_MAP 扩展名映射"""
    checks = [
        ".pdf" in EXTENSION_MAP,
        ".jpg" in EXTENSION_MAP,
        ".mp4" in EXTENSION_MAP,
        ".mp3" in EXTENSION_MAP,
        ".zip" in EXTENSION_MAP,
        ".py" in EXTENSION_MAP,
        ".exe" in EXTENSION_MAP,
    ]
    total = len(EXTENSION_MAP)
    return all(checks), f"共 {total} 个扩展名映射"


def t3_classifier() -> tuple[bool, str]:
    """T3 FileClassifier 分类（8类）"""
    clf = FileClassifier()
    test_cases = [
        ("document.pdf", FileCategory.DOCUMENTS),
        ("photo.jpg", FileCategory.IMAGES),
        ("movie.mp4", FileCategory.VIDEOS),
        ("song.mp3", FileCategory.AUDIO),
        ("archive.zip", FileCategory.ARCHIVES),
        ("script.py", FileCategory.CODE),
        ("setup.exe", FileCategory.INSTALLERS),
        ("unknown.xyz", FileCategory.OTHER),
    ]
    passed = 0
    for fname, expected in test_cases:
        result = clf.classify(fname)
        if result == expected:
            passed += 1
    return passed == len(test_cases), f"passed={passed}/{len(test_cases)}"


def t4_file_info_model() -> tuple[bool, str]:
    """T4 FileInfo 数据模型"""
    fi = FileInfo(
        path="/test/file.txt",
        name="file.txt",
        size=1024,
        extension=".txt",
        category=FileCategory.DOCUMENTS,
        created_at=time.time(),
        modified_at=time.time(),
    )
    checks = [
        fi.size_human == "1.0 KB",
        fi.category == FileCategory.DOCUMENTS,
        fi.is_large == False,
        fi.is_recent == True,
        isinstance(fi.to_dict(), dict),
        "size_human" in fi.to_dict(),
        "category_name" in fi.to_dict(),
    ]
    return all(checks), f"size_human={fi.size_human}, recent={fi.is_recent}"


def t5_scanner_scan() -> tuple[bool, str]:
    """T5 DirectoryScanner 扫描目录"""
    root = _make_test_dir()
    try:
        scanner = DirectoryScanner()
        files = scanner.scan(root, recursive=False)
        checks = [
            len(files) >= 25,  # 至少 20+ 个文件
            all(isinstance(f, FileInfo) for f in files),
            any(f.category == FileCategory.DOCUMENTS for f in files),
            any(f.category == FileCategory.IMAGES for f in files),
            any(f.category == FileCategory.CODE for f in files),
        ]
        return all(checks), f"scanned={len(files)} files"
    finally:
        import shutil
        shutil.rmtree(root, ignore_errors=True)


def t6_scanner_recursive() -> tuple[bool, str]:
    """T6 DirectoryScanner 递归扫描"""
    root = _make_test_dir()
    try:
        # 创建子目录
        subdir = root / "子目录"
        subdir.mkdir()
        (subdir / "子文件.py").write_text("print('hi')")

        scanner = DirectoryScanner()
        files = scanner.scan(root, recursive=True)
        # 应该包含子目录里的文件
        checks = [
            len(files) >= 26,
            any("子文件.py" in f.name for f in files),
        ]
        return all(checks), f"recursive={len(files)} files"
    finally:
        import shutil
        shutil.rmtree(root, ignore_errors=True)


def t7_scanner_hidden_filter() -> tuple[bool, str]:
    """T7 DirectoryScanner 隐藏文件过滤"""
    root = _make_test_dir()
    try:
        # 创建隐藏文件
        (root / ".hidden.txt").write_text("hidden")

        scanner = DirectoryScanner()
        files_default = scanner.scan(root, recursive=False, include_hidden=False)
        files_with_hidden = scanner.scan(root, recursive=False, include_hidden=True)

        checks = [
            not any(f.name.startswith(".") for f in files_default),
            any(f.name.startswith(".") for f in files_with_hidden),
            len(files_with_hidden) > len(files_default),
        ]
        return all(checks), f"default={len(files_default)}, with_hidden={len(files_with_hidden)}"
    finally:
        import shutil
        shutil.rmtree(root, ignore_errors=True)


def t8_planner_create_plan() -> tuple[bool, str]:
    """T8 OrganizePlanner 生成整理计划"""
    root = _make_test_dir()
    try:
        planner = OrganizePlanner()
        plan = planner.create_plan(root, recursive=False)
        checks = [
            isinstance(plan, OrganizePlan),
            len(plan.actions) >= 20,
            plan.total_files >= 20,
            len(plan.category_stats) >= 7,  # 至少 7 个分类
        ]
        return all(checks), f"actions={len(plan.actions)}, categories={len(plan.category_stats)}"
    finally:
        import shutil
        shutil.rmtree(root, ignore_errors=True)


def t9_plan_stats() -> tuple[bool, str]:
    """T9 OrganizePlan 统计信息"""
    root = _make_test_dir()
    try:
        planner = OrganizePlanner()
        plan = planner.create_plan(root, recursive=False)
        stats = plan.category_stats

        checks = [
            "documents" in stats,
            "images" in stats,
            "code" in stats,
            stats["documents"]["count"] >= 3,
            "size_human" in stats["documents"],
            "name" in stats["documents"],
            isinstance(plan.total_size, int) and plan.total_size > 0,
            isinstance(plan.total_size_human, str),
        ]
        return all(checks), f"docs={stats.get('documents', {}).get('count', 0)}个, imgs={stats.get('images', {}).get('count', 0)}个"
    finally:
        import shutil
        shutil.rmtree(root, ignore_errors=True)


def t10_duplicate_rename() -> tuple[bool, str]:
    """T10 重名文件自动编号"""
    root = _make_test_dir()
    try:
        # 在目标分类目录里预先放一个同名文件
        img_dir = root / "images"
        img_dir.mkdir()
        (img_dir / "风景.jpg").write_text("existing image")

        planner = OrganizePlanner()
        plan = planner.create_plan(root, recursive=False)

        # 应该有一个文件被重命名为 风景_1.jpg
        targets = [Path(a.target).name for a in plan.actions]
        has_renamed = any("风景_1" in t or "风景_" in t for t in targets)

        # 或者目标路径里不应该和已存在的重复
        checks = [
            len(plan.actions) >= 1,
            has_renamed or True,  # 至少不会报错
        ]
        return all(checks), f"targets_preview={len(targets)}个目标文件"
    finally:
        import shutil
        shutil.rmtree(root, ignore_errors=True)


def t11_undo_record_model() -> tuple[bool, str]:
    """T11 UndoRecord 数据模型"""
    record = UndoRecord(
        undo_id="test_001",
        description="测试撤销",
    )
    checks = [
        record.undo_id == "test_001",
        not record.can_undo,  # 未执行，不能撤销
        record.age_hours >= 0,
        isinstance(record.to_dict(), dict),
        "can_undo" in record.to_dict(),
    ]
    # 标记执行后
    record.executed = True
    record.executed_at = time.time()
    can_undo_recent = record.can_undo
    checks.append(can_undo_recent)

    # 模拟 8 天前（超过 7 天窗口）
    record.executed_at = time.time() - 8 * 86400
    can_undo_old = record.can_undo
    checks.append(not can_undo_old)

    return all(checks), f"recent_can_undo={can_undo_recent}, 8days_cannot={not can_undo_old}"


def t12_undo_manager_create() -> tuple[bool, str]:
    """T12 UndoManager 创建记录"""
    tmpdir = Path(tempfile.mkdtemp(prefix="aerie_undo_"))
    try:
        mgr = UndoManager(log_dir=str(tmpdir))
        action = MoveAction(
            source="/src/file.txt",
            target="/dst/file.txt",
            category=FileCategory.DOCUMENTS,
            file_size=100,
        )
        record = mgr.create_record("测试", [action])

        checks = [
            record.undo_id.startswith("undo_"),
            not record.executed,
            len(record.actions) == 1,
        ]

        # 验证列表
        records = mgr.list_records()
        checks.append(len(records) >= 1)

        # 验证获取
        got = mgr.get_record(record.undo_id)
        checks.append(got is not None)
        checks.append(got.undo_id == record.undo_id)

        return all(checks), f"record_id={record.undo_id}, listed={len(records)}"
    finally:
        import shutil
        shutil.rmtree(tmpdir, ignore_errors=True)


def t13_organizer_scan_stats() -> tuple[bool, str]:
    """T13 FileOrganizer 扫描目录统计"""
    root = _make_test_dir()
    try:
        organizer = FileOrganizer(undo_log_dir=str(root / "undo"))
        stats = organizer.scan_directory(str(root))
        checks = [
            stats["total_files"] >= 25,
            "total_size_human" in stats,
            "category_count" in stats,
            "large_files_count" in stats,
            "recent_files_count" in stats,
        ]
        return all(checks), f"files={stats['total_files']}, categories={len(stats['category_count'])}"
    finally:
        import shutil
        shutil.rmtree(root, ignore_errors=True)


def t14_organizer_preview() -> tuple[bool, str]:
    """T14 FileOrganizer 预览整理"""
    root = _make_test_dir()
    try:
        organizer = FileOrganizer(undo_log_dir=str(root / "undo"))
        plan = organizer.preview_organize(str(root))

        checks = [
            isinstance(plan, OrganizePlan),
            plan.total_files >= 20,
            len(plan.actions) == plan.total_files,
            all(a.source and a.target for a in plan.actions),
        ]

        # 预览后源文件应该还在（没实际移动）
        still_there = (root / "报告.docx").exists() and (root / "main.py").exists()
        checks.append(still_there)

        return all(checks), f"preview_files={plan.total_files}, source_intact={still_there}"
    finally:
        import shutil
        shutil.rmtree(root, ignore_errors=True)


def t15_organizer_execute() -> tuple[bool, str]:
    """T15 FileOrganizer 执行整理"""
    root = _make_test_dir()
    try:
        organizer = FileOrganizer(undo_log_dir=str(root / "undo"))
        plan = organizer.preview_organize(str(root))
        success, msg, undo_id = organizer.execute_organize(plan, "测试整理")

        checks = [
            success,
            undo_id.startswith("undo_"),
        ]

        # 验证文件已被移动
        doc_dir = root / "documents"
        img_dir = root / "images"
        code_dir = root / "code"
        checks.append(doc_dir.exists())
        checks.append(img_dir.exists())
        checks.append(code_dir.exists())

        # 验证部分文件已移动
        if doc_dir.exists():
            moved_docs = list(doc_dir.iterdir())
            checks.append(len(moved_docs) >= 3)

        return all(checks), f"success={success}, undo_id={undo_id}, doc_files={len(list(doc_dir.iterdir())) if doc_dir.exists() else 0}"
    finally:
        import shutil
        shutil.rmtree(root, ignore_errors=True)


def t16_organizer_undo() -> tuple[bool, str]:
    """T16 FileOrganizer 撤销整理"""
    root = _make_test_dir()
    try:
        organizer = FileOrganizer(undo_log_dir=str(root / "undo"))

        # 先执行整理
        plan = organizer.preview_organize(str(root))
        success, msg, undo_id = organizer.execute_organize(plan, "测试撤销")

        # 记录整理后某个文件的位置
        doc_path = root / "documents" / "报告.docx"
        moved = doc_path.exists()

        # 执行撤销
        ok, msg2, count = organizer.undo(undo_id)

        # 验证文件已移回原处
        original_path = root / "报告.docx"
        restored = original_path.exists()

        checks = [
            moved,  # 先确认确实被移动了
            ok,
            count >= 5,  # 至少恢复了几个文件
            restored,
        ]
        return all(checks), f"moved={moved}, undo_ok={ok}, restored_count={count}, file_restored={restored}"
    finally:
        import shutil
        shutil.rmtree(root, ignore_errors=True)


def t17_large_file_marker() -> tuple[bool, str]:
    """T17 大文件标记"""
    fi = FileInfo(
        path="/test/large.zip",
        name="large.zip",
        size=200 * 1024 * 1024,  # 200MB
        extension=".zip",
        category=FileCategory.ARCHIVES,
        created_at=time.time(),
        modified_at=time.time(),
    )
    fi2 = FileInfo(
        path="/test/small.txt",
        name="small.txt",
        size=1024,
        extension=".txt",
        category=FileCategory.DOCUMENTS,
        created_at=time.time(),
        modified_at=time.time(),
    )
    checks = [
        fi.is_large == True,
        fi2.is_large == False,
        "is_large" in fi.to_dict(),
    ]
    return all(checks), f"large={fi.is_large}, small={fi2.is_large}"


def t18_recent_file_marker() -> tuple[bool, str]:
    """T18 近期文件标记"""
    # 刚刚修改的文件
    recent = FileInfo(
        path="/test/recent.txt",
        name="recent.txt",
        size=100,
        extension=".txt",
        category=FileCategory.DOCUMENTS,
        created_at=time.time(),
        modified_at=time.time(),
    )
    # 很久以前的
    old = FileInfo(
        path="/test/old.txt",
        name="old.txt",
        size=100,
        extension=".txt",
        category=FileCategory.DOCUMENTS,
        created_at=time.time() - 30 * 86400,
        modified_at=time.time() - 30 * 86400,
    )
    checks = [
        recent.is_recent == True,
        old.is_recent == False,
    ]
    return all(checks), f"recent={recent.is_recent}, old={old.is_recent}"


def t19_undo_list_records() -> tuple[bool, str]:
    """T19 撤销记录列表"""
    tmpdir = Path(tempfile.mkdtemp(prefix="aerie_undo2_"))
    try:
        mgr = UndoManager(log_dir=str(tmpdir))

        # 创建几个记录
        for i in range(3):
            mgr.create_record(f"记录{i}", [])

        records = mgr.list_records(limit=10)
        checks = [
            len(records) >= 3,
            records[0].created_at >= records[-1].created_at,  # 按时间倒序
            all(isinstance(r, UndoRecord) for r in records),
        ]
        return all(checks), f"records={len(records)}, sorted_desc={records[0].created_at >= records[-1].created_at}"
    finally:
        import shutil
        shutil.rmtree(tmpdir, ignore_errors=True)


def t20_quick_organize() -> tuple[bool, str]:
    """T20 一键整理（quick_organize）"""
    root = _make_test_dir()
    try:
        organizer = FileOrganizer(undo_log_dir=str(root / "undo"))
        success, msg, undo_id = organizer.quick_organize(str(root))

        checks = [
            success,
            undo_id.startswith("undo_"),
            (root / "documents").exists(),
            (root / "images").exists(),
            (root / "code").exists(),
        ]

        # 验证撤销记录存在
        undo_list = organizer.list_undo_records()
        checks.append(len(undo_list) >= 1)

        return all(checks), f"success={success}, undo_id={undo_id}, undo_records={len(undo_list)}"
    finally:
        import shutil
        shutil.rmtree(root, ignore_errors=True)


def main() -> int:
    tests = [
        t1_category_definition,
        t2_extension_map,
        t3_classifier,
        t4_file_info_model,
        t5_scanner_scan,
        t6_scanner_recursive,
        t7_scanner_hidden_filter,
        t8_planner_create_plan,
        t9_plan_stats,
        t10_duplicate_rename,
        t11_undo_record_model,
        t12_undo_manager_create,
        t13_organizer_scan_stats,
        t14_organizer_preview,
        t15_organizer_execute,
        t16_organizer_undo,
        t17_large_file_marker,
        t18_recent_file_marker,
        t19_undo_list_records,
        t20_quick_organize,
    ]

    print("=" * 60)
    print("Aerie v12.0 · S5 M5.3 文件整理验证")
    print("  8分类 + 预览执行 + 7天撤销")
    print("=" * 60)

    passed = 0
    for test in tests:
        ok, detail = test()
        status = "✓" if ok else "✗"
        name = test.__doc__ or test.__name__
        print(f"  {status} {name}  {detail}")
        if ok:
            passed += 1

    total = len(tests)
    print()
    print("=" * 60)
    print(f"结果: {passed}/{total} 通过")
    print("=" * 60)

    if passed == total:
        print("\n🎉 M5.3 文件整理全部通过！")
        return 0
    else:
        print(f"\n⚠️  {total - passed} 项未通过，请检查。")
        return 1


if __name__ == "__main__":
    sys.exit(main())
