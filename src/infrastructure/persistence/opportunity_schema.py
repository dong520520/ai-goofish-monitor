"""Additive, repeatable schema on the existing application connection."""

STATEMENTS = (
    """CREATE TABLE IF NOT EXISTS categories (
        name TEXT PRIMARY KEY, parent TEXT REFERENCES categories(name), keywords_json TEXT NOT NULL)""",
    """CREATE TABLE IF NOT EXISTS keyword_seeds (
        id INTEGER PRIMARY KEY, category TEXT NOT NULL REFERENCES categories(name), keyword TEXT NOT NULL,
        origin TEXT NOT NULL, discovered_at TEXT NOT NULL, UNIQUE(category, keyword))""",
    """CREATE TABLE IF NOT EXISTS opportunity_items (
        id INTEGER PRIMARY KEY, source TEXT NOT NULL, source_item_id TEXT NOT NULL,
        category TEXT NOT NULL, title TEXT NOT NULL, currency TEXT NOT NULL,
        first_observed_at TEXT NOT NULL, observed_at TEXT NOT NULL, payload_json TEXT NOT NULL,
        UNIQUE(source, source_item_id))""",
    """CREATE TABLE IF NOT EXISTS opportunity_observations (
        id INTEGER PRIMARY KEY, item_id INTEGER NOT NULL REFERENCES opportunity_items(id),
        observed_at TEXT NOT NULL, payload_json TEXT NOT NULL, fingerprint TEXT NOT NULL,
        UNIQUE(item_id, fingerprint))""",
    """CREATE TABLE IF NOT EXISTS opportunity_scores (
        item_id INTEGER NOT NULL REFERENCES opportunity_items(id), strategy TEXT NOT NULL,
        score_total REAL NOT NULL, confidence_score REAL NOT NULL, net_margin REAL,
        payload_json TEXT NOT NULL, PRIMARY KEY(item_id, strategy))""",
    """CREATE TABLE IF NOT EXISTS cost_assumptions (
        item_id INTEGER PRIMARY KEY REFERENCES opportunity_items(id), payload_json TEXT NOT NULL,
        updated_at TEXT NOT NULL)""",
    """CREATE TABLE IF NOT EXISTS experiments (
        item_id INTEGER PRIMARY KEY REFERENCES opportunity_items(id), strategy TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'candidate', created_at TEXT NOT NULL)""",
    """CREATE TABLE IF NOT EXISTS opportunity_imports (
        id INTEGER PRIMARY KEY, imported_at TEXT NOT NULL, origin TEXT NOT NULL,
        accepted INTEGER NOT NULL, rejected INTEGER NOT NULL, errors_json TEXT NOT NULL)""",
    """CREATE TABLE IF NOT EXISTS discovery_jobs (
        id INTEGER PRIMARY KEY, keyword_id INTEGER NOT NULL REFERENCES keyword_seeds(id),
        lane TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'pending_manual', created_at TEXT NOT NULL,
        UNIQUE(keyword_id))""",
    "CREATE INDEX IF NOT EXISTS idx_opportunity_category ON opportunity_items(category, source, currency)",
    "CREATE INDEX IF NOT EXISTS idx_opportunity_ranking ON opportunity_scores(strategy, score_total DESC, item_id)",
    "CREATE INDEX IF NOT EXISTS idx_opportunity_observation_time ON opportunity_observations(item_id, observed_at)",
)

DEFAULT_CATEGORIES = {
    "数码家电": {"电脑外设": ["键盘", "鼠标", "显示器", "扩展坞"], "手机摄影": ["手机", "相机", "镜头"], "家电": ["咖啡机", "吸尘器", "电饭煲"]},
    "居家生活": {"家居收纳": ["收纳", "置物架", "台灯"], "厨具园艺": ["花盆", "厨具", "水壶"]},
    "服饰美妆": {"服装配饰": ["外套", "背包", "围巾"], "美妆个护": ["化妆镜", "美甲", "理发器"]},
    "兴趣运动": {"户外运动": ["露营", "帐篷", "骑行", "瑜伽"], "乐器玩具": ["吉他", "积木", "模型"]},
    "母婴宠物": {"母婴用品": ["婴儿车", "绘本"], "宠物用品": ["猫砂盆", "宠物", "猫抓板"]},
    "办公学习": {"图书文具": ["图书", "文具", "笔记本"], "办公设备": ["打印机", "标签机", "扫描仪"]},
    "汽车工具": {"汽摩配件": ["车载", "头盔"], "五金工具": ["电钻", "螺丝刀", "工具箱"]},
    "虚拟与服务": {"原创数字作品": ["原创模板", "原创插画", "原创字体"], "技能服务": ["设计服务", "维修服务", "翻译服务"]},
}


def init_opportunity_schema(conn):
    for statement in STATEMENTS:
        conn.execute(statement)
    conn.execute("INSERT OR IGNORE INTO categories VALUES ('未分类', NULL, '[]')")
    # Seed once: user-edited categories/keywords are never overwritten on startup.
    if conn.execute("SELECT 1 FROM app_metadata WHERE key='migration:opportunities_v1'").fetchone():
        return
    import json
    from datetime import datetime, timezone
    stamp = datetime.now(timezone.utc).isoformat()
    for parent, children in DEFAULT_CATEGORIES.items():
        conn.execute("INSERT OR IGNORE INTO categories VALUES (?, NULL, '[]')", (parent,))
        for name, keywords in children.items():
            conn.execute("INSERT OR IGNORE INTO categories VALUES (?, ?, ?)", (name, parent, json.dumps(keywords, ensure_ascii=False)))
            for keyword in keywords:
                conn.execute("INSERT OR IGNORE INTO keyword_seeds(category,keyword,origin,discovered_at) VALUES (?,?,?,?)", (name, keyword, "default_seed", stamp))
    conn.execute("INSERT INTO app_metadata VALUES ('migration:opportunities_v1','done')")
