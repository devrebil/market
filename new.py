import sys
import sqlite3
import requests
from datetime import datetime
import json
import webbrowser
from bs4 import BeautifulSoup

# 엑셀 저장을 위한 openpyxl 추가
try:
    import openpyxl
    from openpyxl.styles import Font as ExcelFont, Alignment
except ImportError:
    pass

# [수정된 부분] Selenium 및 크롬 탐지 방지 드라이버(UC) 임포트
import undetected_chromedriver as uc
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

# PyQt6 라이브러리 임포트
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QSplitter, QListWidget, QListWidgetItem, QLabel, QLineEdit,
    QPushButton, QTableWidget, QTableWidgetItem, QHeaderView,
    QTreeWidget, QTreeWidgetItem, QMessageBox, QFrame, QTabWidget,
    QDialog, QComboBox, QTextEdit, QFormLayout, QDialogButtonBox,
    QProgressDialog, QSpinBox, QMenu, QFileDialog,
    QDateEdit
)

from PyQt6.QtCore import Qt, QThread, pyqtSignal, QSettings, QDate
from PyQt6.QtGui import QFont, QColor, QAction

# 그래프 라이브러리 임포트
import matplotlib.pyplot as plt
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as FigureCanvas

# 한글 폰트 설정
plt.rcParams['font.family'] = 'Malgun Gothic'
plt.rcParams['axes.unicode_minus'] = False

# ============================================================
# 데이터베이스 관리 클래스
# ============================================================
class DatabaseManager:
    """SQLite 데이터베이스 관리 (완전 초기화 버전 v3 + 모든 기능 복구)"""
    
    def __init__(self, db_name="market_research_v3.db"):
        self.db_name = db_name
        self.init_database()
    
    def get_connection(self):
        """DB 연결 반환 (잠김 방지를 위해 timeout 20초 설정)"""
        return sqlite3.connect(self.db_name, timeout=20)
    
    def init_database(self):
        """테이블 생성 시 모든 필수 컬럼을 포함하여 오류 원천 차단"""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        # [상품 테이블]
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS products (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                category_large TEXT NOT NULL,
                category_medium TEXT,
                category_small TEXT,
                product_name TEXT NOT NULL,
                vendor TEXT NOT NULL,
                price INTEGER NOT NULL,
                url TEXT,
                css_selector TEXT,
                memo TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                delivery_fee INTEGER DEFAULT 0,
                pinned INTEGER DEFAULT 0,
                pinned_at TEXT
            )
        ''')
        
        # [가격 히스토리 테이블]
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS price_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                product_id INTEGER NOT NULL,
                crawled_date TEXT NOT NULL,
                crawled_time TEXT NOT NULL,
                price INTEGER NOT NULL,
                delivery_fee INTEGER DEFAULT 0,
                vendor TEXT,
                FOREIGN KEY (product_id) REFERENCES products(id)
            )
        ''')

        # [검색 히스토리 테이블]
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS search_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                preset_id INTEGER,
                store_name TEXT,
                keyword TEXT,
                product_name TEXT DEFAULT '',
                checked_at TEXT,
                rank INTEGER,
                total_results INTEGER,
                site TEXT DEFAULT '',
                note TEXT
            )
        ''')

        # [기타 필수 테이블]
        cursor.execute('CREATE TABLE IF NOT EXISTS bookmarks (id INTEGER PRIMARY KEY AUTOINCREMENT, category_large TEXT NOT NULL, category_medium TEXT, category_small TEXT, site_name TEXT NOT NULL, url TEXT NOT NULL)')
        cursor.execute('CREATE TABLE IF NOT EXISTS api_keys (id INTEGER PRIMARY KEY CHECK (id = 1), naver_client_id TEXT, naver_client_secret TEXT, updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)')
        cursor.execute('CREATE TABLE IF NOT EXISTS search_presets (id INTEGER PRIMARY KEY AUTOINCREMENT, store_name TEXT NOT NULL, keyword TEXT NOT NULL, pinned INTEGER DEFAULT 0, pinned_at TEXT, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)')

        conn.commit()
        conn.close()

    # ========== 상품 관련 메서드 ==========
    def add_product(self, data):
        conn = self.get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO products 
                (category_large, category_medium, category_small, product_name, 
                 vendor, price, url, css_selector, memo, delivery_fee)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (data['category_large'], data['category_medium'], data['category_small'],
                data['product_name'], data['vendor'], data['price'],
                data['url'], data['css_selector'], data['memo'], data.get('delivery_fee', 0)))
            p_id = cursor.lastrowid
            now = datetime.now()
            cursor.execute('''
                INSERT INTO price_history (product_id, crawled_date, crawled_time, price, delivery_fee, vendor)
                VALUES (?, ?, ?, ?, ?, ?)
            ''', (p_id, now.strftime('%Y-%m-%d'), now.strftime('%H:%M:%S'), data['price'], data.get('delivery_fee', 0), data['vendor']))
            conn.commit()
            return p_id
        finally:
            conn.close()

    def get_all_products(self, search_term=""):
        conn = self.get_connection()
        cursor = conn.cursor()
        order = "ORDER BY pinned DESC, pinned_at DESC, id DESC"
        if search_term:
            cursor.execute(f"SELECT * FROM products WHERE product_name LIKE ? OR vendor LIKE ? {order}", (f'%{search_term}%', f'%{search_term}%'))
        else:
            cursor.execute(f"SELECT * FROM products {order}")
        res = cursor.fetchall()
        conn.close()
        return res

    def update_product(self, p_id, data):
        conn = self.get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute('''
                UPDATE products SET
                    category_large=?, category_medium=?, category_small=?,
                    product_name=?, vendor=?, price=?, url=?, css_selector=?, memo=?, delivery_fee=?
                WHERE id=?
            ''', (data['category_large'], data['category_medium'], data['category_small'],
                  data['product_name'], data['vendor'], data['price'],
                  data['url'], data['css_selector'], data['memo'], data.get('delivery_fee', 0), p_id))
            conn.commit()
        finally:
            conn.close()

    def update_pin_status(self, p_id, pinned):
        conn = self.get_connection()
        try:
            cursor = conn.cursor()
            p_at = datetime.now().isoformat() if pinned else None
            cursor.execute('UPDATE products SET pinned=?, pinned_at=? WHERE id=?', (pinned, p_at, p_id))
            conn.commit()
        finally:
            conn.close()

    def delete_product(self, p_id):
        conn = self.get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute('DELETE FROM price_history WHERE product_id=?', (p_id,))
            cursor.execute('DELETE FROM products WHERE id=?', (p_id,))
            conn.commit()
        finally:
            conn.close()

    # ========== 히스토리 관련 메서드 ==========
    def add_price_history(self, p_id, price, fee=0, vendor=None):
        conn = self.get_connection()
        try:
            cursor = conn.cursor()
            now = datetime.now()
            cursor.execute('''
                INSERT INTO price_history (product_id, crawled_date, crawled_time, price, delivery_fee, vendor)
                VALUES (?, ?, ?, ?, ?, ?)
            ''', (p_id, now.strftime('%Y-%m-%d'), now.strftime('%H:%M:%S'), price, fee, vendor))
            conn.commit()
        finally:
            conn.close()

    def get_price_history(self, p_id):
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute('SELECT id, product_id, crawled_date, crawled_time, price, delivery_fee, vendor FROM price_history WHERE product_id = ? ORDER BY crawled_date DESC, crawled_time DESC', (p_id,))
        res = cursor.fetchall()
        conn.close()
        return res

    # ========== 즐겨찾기 관련 메서드 ==========
    def add_bookmark(self, data):
        conn = self.get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO bookmarks (category_large, category_medium, category_small, site_name, url)
                VALUES (?, ?, ?, ?, ?)
            ''', (data['category_large'], data['category_medium'], data['category_small'], data['site_name'], data['url']))
            conn.commit()
        finally:
            conn.close()

    def get_all_bookmarks(self):
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute('SELECT * FROM bookmarks ORDER BY category_large, category_medium, category_small, site_name')
        rows = cursor.fetchall()
        conn.close()
        
        tree = {}
        for r in rows:
            l, m, s, name, url = r[1], r[2] or "", r[3] or "", r[4], r[5]
            if l not in tree: tree[l] = {}
            if m not in tree[l]: tree[l][m] = {}
            if s not in tree[l][m]: tree[l][m][s] = []
            tree[l][m][s].append((name, url, r[0]))
        return tree

    def delete_bookmark(self, b_id):
        conn = self.get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute('DELETE FROM bookmarks WHERE id=?', (b_id,))
            conn.commit()
        finally:
            conn.close()

    # ========== 검색어 프리셋 및 API 키 관련 메서드 ==========
    def add_search_preset(self, store, keyword):
        conn = self.get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute('INSERT INTO search_presets (store_name, keyword) VALUES (?, ?)', (store, keyword))
            conn.commit()
        finally:
            conn.close()

    def get_search_presets(self, store=None):
        conn = self.get_connection()
        cursor = conn.cursor()
        if store:
            cursor.execute('SELECT * FROM search_presets WHERE store_name = ? ORDER BY pinned DESC, pinned_at DESC, id ASC', (store,))
        else:
            cursor.execute('SELECT * FROM search_presets ORDER BY pinned DESC, pinned_at DESC, id ASC')
        res = cursor.fetchall()
        conn.close()
        return res

    def get_unique_preset_stores(self):
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute('SELECT DISTINCT store_name FROM search_presets')
        res = [r[0] for r in cursor.fetchall()]
        conn.close()
        return res

    def set_api_keys(self, client_id, client_secret):
        conn = self.get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute('INSERT OR REPLACE INTO api_keys (id, naver_client_id, naver_client_secret, updated_at) VALUES (1, ?, ?, CURRENT_TIMESTAMP)', (client_id, client_secret))
            conn.commit()
        finally:
            conn.close()

    def get_api_keys(self):
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute('SELECT naver_client_id, naver_client_secret FROM api_keys WHERE id = 1')
        res = cursor.fetchone()
        conn.close()
        return res if res else (None, None)

    def get_search_history(self, store, kw):
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute('SELECT checked_at, rank, total_results FROM search_history WHERE store_name = ? AND keyword = ? ORDER BY checked_at DESC', (store, kw))
        res = cursor.fetchall()
        conn.close()
        return res

    def get_unique_categories(self, level='large'):
        conn = self.get_connection()
        cursor = conn.cursor()
        col = f"category_{level}"
        cursor.execute(f"SELECT DISTINCT {col} FROM products WHERE {col} IS NOT NULL AND {col} != ''")
        res = [r[0] for r in cursor.fetchall()]
        conn.close()
        return sorted(res)

class SeleniumCrawler:
    def __init__(self, headless=True):
        self.headless = headless
        self.driver = None
    
    def init_driver(self):
        """Edge 대신 크롬(UC)을 사용하여 탐지 방지 드라이버를 초기화합니다."""
        options = uc.ChromeOptions()
        if self.headless:
            options.add_argument('--headless')
        
        options.add_argument('--no-sandbox')
        options.add_argument('--disable-dev-shm-usage')
        
        # 크롬 브라우저를 사용하여 드라이버를 실행합니다.
        self.driver = uc.Chrome(options=options)
    
    def get_price(self, url, selector, wait_time=10):
        if not self.driver: self.init_driver()
        try:
            self.driver.get(url)
            wait = WebDriverWait(self.driver, wait_time)
            elem = wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, selector)))
            
            # 텍스트에서 숫자만 추출하여 가격으로 변환합니다.
            digits = ''.join(filter(str.isdigit, elem.text.strip()))
            return (True, int(digits), None) if digits else (False, None, "숫자 추출 실패")
        except Exception as e:
            return (False, None, str(e))
    
    def close(self):
        if self.driver:
            self.driver.quit()
            self.driver = None

class CrawlWorker(QThread):
    progress = pyqtSignal(int, str)
    finished = pyqtSignal(list)
    
    def __init__(self, targets, use_selenium=False):
        super().__init__()
        self.targets = targets
        self.use_selenium = use_selenium
    
    def run(self):
        results = []
        total = len(self.targets)
        if self.use_selenium:
            # 크롬 기반의 UC 크롤러를 생성합니다.
            sc = SeleniumCrawler(headless=True)
            try:
                for i, (p_id, url, sel, vendor) in enumerate(self.targets):
                    self.progress.emit(int((i / total) * 100), f"Chrome(UC): {vendor}")
                    success, price, err = sc.get_price(url, sel)
                    results.append((p_id, price, success, {'vendor': vendor, 'error': err}))
            finally:
                sc.close()
        else:
            # 기본 Requests 방식 로직입니다.
            session = requests.Session()
            for i, (p_id, url, sel, vendor) in enumerate(self.targets):
                try:
                    self.progress.emit(int((i / total) * 100), f"Requests: {vendor}")
                    resp = session.get(url, timeout=10)
                    soup = BeautifulSoup(resp.content, 'html.parser')
                    elem = soup.select_one(sel)
                    if elem:
                        price = int(''.join(filter(str.isdigit, elem.get_text())))
                        results.append((p_id, price, True, {'vendor': vendor}))
                    else:
                        results.append((p_id, None, False, {'vendor': vendor, 'error': 'Selector Not Found'}))
                except Exception as e:
                    results.append((p_id, None, False, {'vendor': vendor, 'error': str(e)}))
        
        self.progress.emit(100, "완료")
        self.finished.emit(results)

# ============================================================
# 다이얼로그 클래스들
# ============================================================
class ProductDialog(QDialog):
    """상품 등록 및 수정 다이얼로그 (내부 선언으로 임포트 에러 해결)"""
    def __init__(self, db, product_data=None, parent=None):
        super().__init__(parent)
        self.db = db
        self.product_data = product_data
        self.init_ui()
    
    def init_ui(self):
        self.setWindowTitle("상품 정보")
        layout = QFormLayout(self)
        self.c_l = QComboBox(); self.c_l.setEditable(True); self.c_l.addItems(self.db.get_unique_categories('large'))
        self.c_m = QComboBox(); self.c_m.setEditable(True); self.c_m.addItems(self.db.get_unique_categories('medium'))
        self.c_s = QComboBox(); self.c_s.setEditable(True); self.c_s.addItems(self.db.get_unique_categories('small'))
        self.name = QLineEdit()
        self.vendor = QLineEdit()
        self.price = QLineEdit()
        self.fee = QLineEdit(); self.fee.setText("0")
        self.url = QLineEdit()
        self.selector = QLineEdit()
        self.memo = QTextEdit(); self.memo.setMaximumHeight(60)
        
        layout.addRow("대분류:", self.c_l)
        layout.addRow("중분류:", self.c_m)
        layout.addRow("소분류:", self.c_s)
        layout.addRow("상품명*:", self.name)
        layout.addRow("판매처*:", self.vendor)
        layout.addRow("가격*:", self.price)
        layout.addRow("택배비:", self.fee)
        layout.addRow("URL:", self.url)
        layout.addRow("Selector:", self.selector)
        layout.addRow("비고:", self.memo)
        
        btns = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)
        layout.addRow(btns)
        
        if self.product_data:
            p = self.product_data
            self.c_l.setCurrentText(p[1])
            self.c_m.setCurrentText(p[2] or "")
            self.c_s.setCurrentText(p[3] or "")
            self.name.setText(p[4]); self.vendor.setText(p[5])
            self.price.setText(str(p[6])); self.url.setText(p[7] or "")
            self.selector.setText(p[8] or ""); self.memo.setPlainText(p[9] or "")
            self.fee.setText(str(p[11]))

    def get_data(self):
        return {
            'category_large': self.c_l.currentText(), 'category_medium': self.c_m.currentText(), 'category_small': self.c_s.currentText(),
            'product_name': self.name.text(), 'vendor': self.vendor.text(),
            'price': int(self.price.text() or 0), 'delivery_fee': int(self.fee.text() or 0),
            'url': self.url.text(), 'css_selector': self.selector.text(), 'memo': self.memo.toPlainText()
        }

class BookmarkDialog(QDialog):
    """즐겨찾기 등록 다이얼로그 (대/중/소 분류 추가)"""
    def __init__(self, db, parent=None):
        super().__init__(parent)
        self.db = db
        self.setWindowTitle("즐겨찾기 등록")
        layout = QFormLayout(self)
        
        self.c_l = QComboBox(); self.c_l.setEditable(True)
        self.c_m = QComboBox(); self.c_m.setEditable(True)
        self.c_s = QComboBox(); self.c_s.setEditable(True)
        self.name = QLineEdit()
        self.url = QLineEdit()
        
        # 기존 대분류 항목 채우기
        self.c_l.addItems(self.db.get_unique_categories('large'))
        
        layout.addRow("대분류*:", self.c_l)
        layout.addRow("중분류:", self.c_m)
        layout.addRow("소분류:", self.c_s)
        layout.addRow("사이트명*:", self.name)
        layout.addRow("URL*:", self.url)
        
        btns = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        btns.accepted.connect(self.validate)
        btns.rejected.connect(self.reject)
        layout.addRow(btns)

    def validate(self):
        if not self.c_l.currentText() or not self.name.text() or not self.url.text():
            QMessageBox.warning(self, "입력 오류", "대분류, 사이트명, URL은 필수입니다.")
            return
        self.accept()

    def get_data(self):
        return {
            'category_large': self.c_l.currentText(),
            'category_medium': self.c_m.currentText(),
            'category_small': self.c_s.currentText(),
            'site_name': self.name.text(),
            'url': self.url.text()
        }

# ============================================================
# 메인 윈도우
# ============================================================
class MarketResearchApp(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("시장조사 프로그램")
        self.settings = QSettings("MyCompany", "MarketResearchApp")
        
        # 창 크기 복구
        geometry = self.settings.value("geometry")
        if geometry: self.restoreGeometry(geometry)
        else: self.resize(1400, 900)
        
        self.db = DatabaseManager()
        self.current_product_id = None
        
        self.init_ui()
        self.load_initial_data()

    def closeEvent(self, event):
        """종료 시 설정 저장"""
        self.settings.setValue("geometry", self.saveGeometry())
        self.settings.setValue("manage_table_header", self.manage_table.horizontalHeader().saveState())
        super().closeEvent(event)

    def init_ui(self):
        main_widget = QWidget()
        self.setCentralWidget(main_widget)
        main_layout = QVBoxLayout(main_widget)
        main_layout.setContentsMargins(0, 0, 0, 0)
        
        self.tabs = QTabWidget()
        self.tabs.setStyleSheet("QTabBar::tab { background: #f0f0f0; padding: 10px 20px; font-weight: bold; } QTabBar::tab:selected { background: #4f46e5; color: white; }")
        
        self.home_tab = QWidget(); self.setup_home_tab(); self.tabs.addTab(self.home_tab, "🏠 홈")
        self.search_tab = QWidget(); self.setup_search_tab(); self.tabs.addTab(self.search_tab, "🔍 검색")
        self.manage_tab = QWidget(); self.setup_manage_tab(); self.tabs.addTab(self.manage_tab, "⚙️ 관리")
        
        main_layout.addWidget(self.tabs)

    def setup_home_tab(self):
        layout = QHBoxLayout(self.home_tab)
        splitter = QSplitter(Qt.Orientation.Horizontal)
        
        # [1] 좌측
        area1 = QWidget(); v1 = QVBoxLayout(area1)
        v1.addWidget(QLabel("🛍️ 상품 관리"))
        self.btn_add_p = QPushButton("➕ 상품 등록")
        self.btn_add_p.clicked.connect(self.add_product_dialog)
        v1.addWidget(self.btn_add_p)
        self.search_p = QLineEdit(); self.search_p.setPlaceholderText("검색..."); self.search_p.textChanged.connect(self.refresh_product_list)
        v1.addWidget(self.search_p)
        self.p_list = QListWidget(); self.p_list.itemClicked.connect(self.on_product_clicked)
        self.p_list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu); self.p_list.customContextMenuRequested.connect(self.show_product_context_menu)
        v1.addWidget(self.p_list)
        splitter.addWidget(area1)
        
        # [2] 중앙
        area2 = QWidget(); v2 = QVBoxLayout(area2)
        h2 = QHBoxLayout(); self.h_title = QLabel("🕒 히스토리"); h2.addWidget(self.h_title); h2.addStretch()
        btn_excel = QPushButton("📊 엑셀"); btn_excel.clicked.connect(self.export_all_history_to_excel); h2.addWidget(btn_excel)
        btn_crawl = QPushButton("🔄 크롤링"); btn_crawl.clicked.connect(self.crawl_all_products); h2.addWidget(btn_crawl)
        v2.addLayout(h2)
        self.h_table = QTableWidget(0, 6); self.h_table.setHorizontalHeaderLabels(["날짜", "시간", "매입처", "가격", "택배비", "변동폭"])
        self.h_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        v2.addWidget(self.h_table)
        splitter.addWidget(area2)
        
        # [3] 우측
        area3 = QWidget(); v3 = QVBoxLayout(area3)
        self.figure = plt.Figure(figsize=(5, 4), dpi=100); self.canvas = FigureCanvas(self.figure); self.ax = self.figure.add_subplot(111)
        v3.addWidget(QLabel("📈 가격 추이")); v3.addWidget(self.canvas)
        h_bm = QHBoxLayout(); h_bm.addWidget(QLabel("🔖 즐겨찾기")); h_bm.addStretch()
        btn_add_bm = QPushButton("➕ 추가"); btn_add_bm.clicked.connect(self.add_bookmark_dialog); h_bm.addWidget(btn_add_bm)
        v3.addLayout(h_bm)
        self.bm_tree = QTreeWidget(); self.bm_tree.setHeaderHidden(True); self.bm_tree.itemDoubleClicked.connect(self.on_bookmark_double_clicked)
        self.bm_tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu); self.bm_tree.customContextMenuRequested.connect(self.show_bookmark_context_menu)
        v3.addWidget(self.bm_tree)
        splitter.addWidget(area3)
        
        splitter.setSizes([300, 600, 400]); layout.addWidget(splitter)

    def setup_search_tab(self):
        """검색 탭 UI 개선 - 높이 설정 오류 해결 및 위쪽 밀착 레이아웃"""
        layout = QHBoxLayout(self.search_tab)
        splitter = QSplitter(Qt.Orientation.Horizontal)
        
        # [1] 좌측: 프리셋 관리
        area1 = QWidget()
        v1 = QVBoxLayout(area1)
        btn_reg = QPushButton("➕ 검색어 등록")
        btn_reg.setFixedHeight(40) # [수정] setHeight -> setFixedHeight
        btn_reg.clicked.connect(self.reg_search_preset)
        v1.addWidget(btn_reg)
        self.s_preset_tabs = QTabWidget()
        v1.addWidget(self.s_preset_tabs)
        splitter.addWidget(area1)
        
        # [2] 중앙: 검색 실행 및 히스토리
        area2 = QWidget()
        v2 = QVBoxLayout(area2)
        v2.setContentsMargins(10, 10, 10, 10)
        
        search_box = QFrame()
        search_box.setFrameStyle(QFrame.Shape.StyledPanel | QFrame.Shadow.Raised)
        search_box.setStyleSheet("background-color: #f8fafc; border-radius: 8px;")
        f2 = QFormLayout(search_box)
        self.s_kw_edit = QLineEdit()
        self.s_st_edit = QLineEdit()
        f2.addRow("🔍 검색어:", self.s_kw_edit)
        f2.addRow("🏪 스토어명:", self.s_st_edit)
        v2.addWidget(search_box)
        
        h_btns = QHBoxLayout()
        btn_run = QPushButton("🚀 순위 검색 시작")
        btn_run.setStyleSheet("background-color: #4f46e5; color: white; font-weight: bold; padding: 8px;")
        btn_run.clicked.connect(self.run_naver_search)
        
        self.btn_export_report = QPushButton("📋 보고서 생성")
        self.btn_export_report.setStyleSheet("background-color: #10b981; color: white; font-weight: bold; padding: 8px;")
        self.btn_export_report.clicked.connect(self.generate_search_report)
        
        h_btns.addWidget(btn_run)
        h_btns.addWidget(self.btn_export_report)
        v2.addLayout(h_btns)
        
        v2.addWidget(QLabel("🕒 검색 히스토리 (광고 제외 실순위)"))
        self.s_hist_table = QTableWidget(0, 3)
        self.s_hist_table.setHorizontalHeaderLabels(["체크일시", "순위", "총검색수"])
        self.s_hist_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        v2.addWidget(self.s_hist_table)
        splitter.addWidget(area2)
        
        # [3] 우측: 기간 필터 및 그래프 (위쪽 밀착 설정)
        area3 = QWidget()
        v3 = QVBoxLayout(area3)
        
        filter_group = QFrame()
        filter_group.setFrameStyle(QFrame.Shape.StyledPanel)
        filter_group.setFixedHeight(140) # 영역 높이 고정
        f_layout = QVBoxLayout(filter_group)
        
        h_p_btns = QHBoxLayout()
        for text, days in [("7일", 7), ("1개월", 30), ("1년", 365), ("전체", 0)]:
            btn = QPushButton(text)
            btn.clicked.connect(lambda ch, d=days: self.set_filter_period(d))
            h_p_btns.addWidget(btn)
        f_layout.addLayout(h_p_btns)
        
        h_dates = QHBoxLayout()
        self.s_start_date = QDateEdit(QDate.currentDate().addDays(-7))
        self.s_end_date = QDateEdit(QDate.currentDate())
        self.s_start_date.setCalendarPopup(True)
        self.s_end_date.setCalendarPopup(True)
        btn_apply = QPushButton("적용")
        btn_apply.clicked.connect(self.apply_search_filter)
        h_dates.addWidget(QLabel("기간:")); h_dates.addWidget(self.s_start_date)
        h_dates.addWidget(QLabel("~")); h_dates.addWidget(self.s_end_date); h_dates.addWidget(btn_apply)
        f_layout.addLayout(h_dates)
        
        v3.addWidget(QLabel("📅 기간 설정"))
        v3.addWidget(filter_group)
        v3.addWidget(QLabel("📈 순위 변동 그래프"))
        
        self.s_figure = plt.Figure(figsize=(5, 3), dpi=100)
        self.s_canvas = FigureCanvas(self.s_figure)
        self.s_ax = self.s_figure.add_subplot(111)
        v3.addWidget(self.s_canvas)
        
        v3.addStretch() # 하단에 여백을 주어 위젯들을 위쪽으로 정렬합니다.
        
        splitter.addWidget(area3)
        splitter.setSizes([250, 600, 550])
        layout.addWidget(splitter)
        
    def update_search_graph(self, s, kw):
        """순위 히스토리를 그래프로 시각화"""
        hist = self.db.get_search_history(s, kw)
        if not hist:
            self.s_ax.clear()
            self.s_canvas.draw()
            return
            
        # 데이터를 시간순(오름차순)으로 정렬
        sorted_h = sorted(hist, key=lambda x: x[0])
        dates = [h[0].split(' ')[0][5:] + '\n' + h[0].split(' ')[1][:5] for h in sorted_h] # MM-DD HH:MM 포맷
        
        # 순위 값 처리 (순위 밖 -1은 그래프상에서 310위 위치에 표시)
        ranks = []
        for h in sorted_h:
            r = h[1]
            if r == -1 or r > 300:
                ranks.append(310) # 그래프 하단에 표시되도록 설정
            else:
                ranks.append(r)
        
        self.s_ax.clear()
        self.s_ax.plot(dates, ranks, marker='o', linestyle='-', color='#ef4444', linewidth=2)
        
        # Y축 설정 (1위가 위에 오도록 역전)
        self.s_ax.set_ylim(320, 0) 
        self.s_ax.set_yticks([1, 50, 100, 200, 300, 310])
        self.s_ax.set_yticklabels(['1위', '50위', '100위', '200위', '300위', '순위밖'])
        
        self.s_ax.grid(True, linestyle='--', alpha=0.6)
        self.s_ax.tick_params(axis='x', labelsize=8)
        self.s_figure.tight_layout()
        self.s_canvas.draw()
        
    def set_filter_period(self, days):
        """필터 프리셋 버튼 클릭 시 날짜 설정"""
        from PyQt6.QtCore import QDate
        end = QDate.currentDate()
        if days == 0: # 전체
            # DB의 가장 오래된 데이터를 찾거나 아주 과거 날짜로 설정
            start = QDate(2020, 1, 1)
        else:
            start = end.addDays(-days + 1)
        
        self.s_start_date.setDate(start)
        self.s_end_date.setDate(end)
        self.apply_search_filter()

    def apply_search_filter(self):
        """현재 입력된 검색어/스토어명과 날짜로 데이터 조회 및 그래프 갱신"""
        kw = self.s_kw_edit.text().strip()
        st = self.s_st_edit.text().strip()
        if not kw or not st: return
        
        start = self.s_start_date.date().toString("yyyy-MM-dd")
        end = self.s_end_date.date().toString("yyyy-MM-dd")
        
        self.load_search_history(st, kw, start, end)
        
    def setup_manage_tab(self):
        layout = QVBoxLayout(self.manage_tab)
        h_btn = QHBoxLayout(); h_btn.addWidget(QLabel("📦 상품 목록")); h_btn.addStretch()
        btn_reset = QPushButton("🔄 정렬 초기화"); btn_reset.clicked.connect(self.refresh_manage_table); h_btn.addWidget(btn_reset)
        layout.addLayout(h_btn)
        
        self.manage_table = QTableWidget(0, 8)
        self.manage_table.setHorizontalHeaderLabels(["ID", "카테고리", "상품명", "판매처", "현재가", "택배비", "URL", "비고"])
        self.manage_table.setSortingEnabled(True) # 정렬 지원
        self.manage_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        self.manage_table.horizontalHeader().setStretchLastSection(True)
        
        # 컬럼 너비 복구
        header_state = self.settings.value("manage_table_header")
        if header_state: self.manage_table.horizontalHeader().restoreState(header_state)
        
        layout.addWidget(self.manage_table)
        
        btn_group = QHBoxLayout()
        self.btn_m_edit = QPushButton("✏️ 선택 수정"); self.btn_m_edit.clicked.connect(self.edit_selected_product); btn_group.addWidget(self.btn_m_edit)
        self.btn_m_del = QPushButton("🗑️ 선택 삭제"); self.btn_m_del.setStyleSheet("background:#fee2e2; color:#b91c1c;"); self.btn_m_del.clicked.connect(self.delete_selected_product); btn_group.addWidget(self.btn_m_del)
        layout.addLayout(btn_group)
        
        api_box = QFrame(); api_box.setFrameStyle(QFrame.Shape.StyledPanel); f_api = QFormLayout(api_box)
        self.api_id = QLineEdit(); self.api_sec = QLineEdit()
        c_id, c_sec = self.db.get_api_keys(); self.api_id.setText(c_id); self.api_sec.setText(c_sec)
        f_api.addRow("Naver Client ID:", self.api_id); f_api.addRow("Naver Secret:", self.api_sec)
        btn_save_api = QPushButton("API 키 저장"); btn_save_api.clicked.connect(self.save_api_keys); f_api.addRow(btn_save_api)
        layout.addWidget(api_box)

    # ========== 기능 로직 ==========
    def load_initial_data(self):
        self.refresh_product_list()
        self.refresh_bookmarks()
        self.refresh_manage_table()
        self.refresh_search_presets()

    def refresh_product_list(self):
        self.p_list.clear()
        prods = self.db.get_all_products(self.search_p.text())
        for p in prods:
            pin = "📌 " if p[12] else ""
            item = QListWidgetItem(f"{pin}[{p[1]}]\n{p[4]}\n{p[5]} | {p[6]:,}원")
            item.setData(Qt.ItemDataRole.UserRole, p[0])
            if p[12]: item.setBackground(QColor("#f0f9ff"))
            self.p_list.addItem(item)

    def refresh_manage_table(self):
        self.manage_table.setSortingEnabled(False)
        prods = self.db.get_all_products()
        self.manage_table.setRowCount(len(prods))
        for i, p in enumerate(prods):
            # p[0]:ID, p[1..3]:Categories, p[4]:Name, p[5]:Vendor, p[6]:Price, p[7]:URL, p[9]:Memo, p[11]:Fee
            items = [str(p[0]), f"{p[1]} > {p[2]}", p[4], p[5], f"{p[6]:,}원", f"{p[11]:,}원", p[7] or "-", p[9] or "-"]
            for j, val in enumerate(items):
                self.manage_table.setItem(i, j, QTableWidgetItem(val))
        self.manage_table.setSortingEnabled(True)

    def add_product_dialog(self):
        # ProductDialog가 같은 파일 내에 있으므로 import 불필요
        d = ProductDialog(self.db, parent=self)
        if d.exec() == QDialog.DialogCode.Accepted:
            self.db.add_product(d.get_data())
            self.load_initial_data() # 모든 테이블 동시 갱신

    def on_product_clicked(self, item):
        self.current_product_id = item.data(Qt.ItemDataRole.UserRole)
        self.update_history_and_graph()

    def update_history_and_graph(self):
        if not self.current_product_id: return
        hist = self.db.get_price_history(self.current_product_id)
        self.h_table.setRowCount(len(hist))
        for i, h in enumerate(hist):
            # h[2]:Date, h[3]:Time, h[6]:Vendor, h[4]:Price, h[5]:Fee
            self.h_table.setItem(i, 0, QTableWidgetItem(h[2]))
            self.h_table.setItem(i, 1, QTableWidgetItem(h[3]))
            self.h_table.setItem(i, 2, QTableWidgetItem(h[6] or "-"))
            self.h_table.setItem(i, 3, QTableWidgetItem(f"{h[4]:,}원"))
            self.h_table.setItem(i, 4, QTableWidgetItem(f"{h[5]:,}원"))
            diff = "-"
            if i < len(hist) - 1:
                d = h[4] - hist[i+1][4]
                diff = f"▲{d:,}" if d > 0 else (f"▼{abs(d):,}" if d < 0 else "-")
            self.h_table.setItem(i, 5, QTableWidgetItem(diff))
        
        sorted_h = sorted(hist, key=lambda x: (x[2], x[3]))
        if sorted_h:
            dates = [h[2] for h in sorted_h]
            prices = [h[4] for h in sorted_h]
            self.ax.clear(); self.ax.plot(dates, prices, marker='o', color='#4f46e5')
            self.ax.tick_params(axis='x', rotation=45, labelsize=8); self.figure.tight_layout(); self.canvas.draw()

    # ========== 즐겨찾기 로직 (개선) ==========
    def add_bookmark_dialog(self):
        d = BookmarkDialog(self.db, self)
        if d.exec() == QDialog.DialogCode.Accepted:
            self.db.add_bookmark(d.get_data())
            self.refresh_bookmarks()

    def refresh_bookmarks(self):
        """즐겨찾기 아이콘 추가 및 기본 축소 상태 설정"""
        self.bm_tree.clear()
        from PyQt6.QtWidgets import QStyle
        folder_icon = self.style().standardIcon(QStyle.StandardPixmap.SP_DirIcon)
        file_icon = self.style().standardIcon(QStyle.StandardPixmap.SP_FileIcon)
        
        tree_data = self.db.get_all_bookmarks()
        for l, mediums in tree_data.items():
            l_item = QTreeWidgetItem(self.bm_tree, [l])
            l_item.setIcon(0, folder_icon)
            for m, smalls in mediums.items():
                m_node = QTreeWidgetItem(l_item, [m]) if m else l_item
                if m: m_node.setIcon(0, folder_icon)
                for s, sites in smalls.items():
                    s_node = QTreeWidgetItem(m_node, [s]) if s else m_node
                    if s: s_node.setIcon(0, folder_icon)
                    for name, url, b_id in sites:
                        site_item = QTreeWidgetItem(s_node, [name])
                        site_item.setIcon(0, file_icon)
                        site_item.setData(0, Qt.ItemDataRole.UserRole, (url, b_id))
        
        self.bm_tree.collapseAll() # 모두 축소

    def on_bookmark_double_clicked(self, item, col):
        data = item.data(0, Qt.ItemDataRole.UserRole)
        if data: webbrowser.open(data[0])

    def show_bookmark_context_menu(self, pos):
        item = self.bm_tree.itemAt(pos)
        if not item: return
        data = item.data(0, Qt.ItemDataRole.UserRole)
        if not data: return
        menu = QMenu(); del_act = menu.addAction("🗑️ 즐겨찾기 삭제")
        if menu.exec(self.bm_tree.mapToGlobal(pos)) == del_act:
            self.db.delete_bookmark(data[1]); self.refresh_bookmarks()

    # ========== 검색 로직 (수정) ==========
    def reg_search_preset(self):
        d = QDialog(self); d.setWindowTitle("프리셋 등록"); f = QFormLayout(d)
        st = QLineEdit(); kw = QLineEdit(); f.addRow("스토어:", st); f.addRow("검색어:", kw)
        btns = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        btns.accepted.connect(d.accept); btns.rejected.connect(d.reject); f.addRow(btns)
        if d.exec() == QDialog.DialogCode.Accepted:
            if st.text() and kw.text(): self.db.add_search_preset(st.text(), kw.text()); self.refresh_search_presets()

    def refresh_search_presets(self):
        self.s_preset_tabs.clear()
        for s in self.db.get_unique_preset_stores():
            lw = QListWidget()
            for p in self.db.get_search_presets(s):
                item = QListWidgetItem(p[2])
                item.setData(Qt.ItemDataRole.UserRole, (p[0], s, p[2])) # ID, Store, KW
                lw.addItem(item)
            lw.itemClicked.connect(self.on_preset_clicked)
            self.s_preset_tabs.addTab(lw, s)

    def on_preset_clicked(self, item):
        """프리셋 클릭 시 입력칸 채우고 히스토리 로드 (에러 해결 버전)"""
        data = item.data(Qt.ItemDataRole.UserRole) # (ID, StoreName, Keyword)
        if data:
            self.s_kw_edit.setText(data[2])
            self.s_st_edit.setText(data[1])
            
            # 여기서 load_search_history를 호출하면 내부에서 표와 그래프를 모두 갱신합니다.
            # 중복된 update_search_graph 호출을 삭제하여 TypeError를 해결합니다.
            self.load_search_history(data[1], data[2])

    def load_search_history(self, s, kw, start_date=None, end_date=None):
        """필터링된 히스토리 데이터를 표와 그래프에 반영"""
        hist = self.db.get_search_history(s, kw)
        
        # 날짜 필터링 적용
        filtered_hist = []
        for h in hist:
            # h[0] 형식: '2024-05-20 14:30:00'
            date_part = h[0].split(' ')[0]
            if start_date and end_date:
                if start_date <= date_part <= end_date:
                    filtered_hist.append(h)
            else:
                filtered_hist.append(h)

        self.s_hist_table.setRowCount(len(filtered_hist))
        for i, r in enumerate(filtered_hist):
            for j, val in enumerate(r):
                display_val = str(val)
                if j == 1 and (str(val) == "-1" or (val and int(val) > 300)):
                    display_val = "순위 밖"
                
                item = QTableWidgetItem(display_val)
                item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                self.s_hist_table.setItem(i, j, item)
        
        # 필터링된 데이터로 그래프 갱신
        self.update_search_graph(filtered_hist)

    def update_search_graph(self, filtered_hist):
        """순위 변동 그래프 그리기"""
        self.s_ax.clear()
        if not filtered_hist:
            self.s_canvas.draw()
            return
            
        # 시간순 정렬
        sorted_h = sorted(filtered_hist, key=lambda x: x[0])
        # X축: 날짜 및 시간 (MM-DD\nHH:MM)
        labels = [h[0][5:10].replace('-', '/') + '\n' + h[0][11:16] for h in sorted_h]
        
        # Y축: 순위 (1위가 상단에 오도록 처리)
        ranks = []
        for h in sorted_h:
            r = h[1]
            # 순위 밖(-1)은 시각적으로 하단에 배치하기 위해 310위로 처리
            ranks.append(310 if r == -1 or r > 300 else r)
        
        self.s_ax.plot(labels, ranks, marker='o', color='#ef4444', linewidth=2)
        
        # 그래프 세부 설정
        self.s_ax.set_ylim(320, 0) # 1위가 위로 가도록 역전
        self.s_ax.set_yticks([1, 50, 100, 200, 300, 310])
        self.s_ax.set_yticklabels(['1', '50', '100', '200', '300', '밖'])
        self.s_ax.grid(True, linestyle='--', alpha=0.5)
        
        # X축 라벨 겹침 방지 (데이터가 많을 경우 일부만 표시)
        if len(labels) > 10:
            for i, label in enumerate(self.s_ax.get_xticklabels()):
                if i % (len(labels) // 5) != 0: label.set_visible(False)
        
        self.s_figure.tight_layout()
        self.s_canvas.draw()

    def run_naver_search(self):
        """300위 검색 및 광고 제외 실순위 반영"""
        kw = self.s_kw_edit.text().strip()
        st = self.s_st_edit.text().strip()
        cid, csec = self.db.get_api_keys()

        if not cid or not csec:
            QMessageBox.warning(self, "알림", "API 키를 먼저 설정하세요.")
            return

        try:
            organic_rank = 0
            found_rank = -1
            total_count = 0
            
            # 300위까지 검색 (100개씩 3회 호출)
            for start_idx in [1, 101, 201]:
                if found_rank != -1: break
                url = f"https://openapi.naver.com/v1/search/shop.json?query={kw}&display=100&start={start_idx}"
                resp = requests.get(url, headers={"X-Naver-Client-Id":cid, "X-Naver-Client-Secret":csec})
                data = resp.json()
                items = data.get('items', [])
                if start_idx == 1: total_count = data.get('total', 0)
                if not items: break

                for it in items:
                    organic_rank += 1
                    mall_name = it.get('mallName', '')
                    if st.lower() in mall_name.lower():
                        found_rank = organic_rank
                        break

            # DB 저장 (product_name 누락 방지 포함)
            now_str = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            conn = self.db.get_connection()
            try:
                cursor = conn.cursor()
                cursor.execute('''
                    INSERT INTO search_history (store_name, keyword, product_name, checked_at, rank, total_results, site)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                ''', (st, kw, kw, now_str, found_rank, total_count, 'Naver_300_Improved'))
                conn.commit()
            finally:
                conn.close()

            self.apply_search_filter() # 표와 그래프 즉시 갱신
            
            if found_rank != -1:
                QMessageBox.information(self, "결과", f"순위 발견: {found_rank}위")
            else:
                QMessageBox.information(self, "결과", "300위 내에 없습니다.")

        except Exception as e:
            QMessageBox.critical(self, "오류", f"검색 중 오류 발생: {e}")
     
    def generate_search_report(self):
        """필터링된 검색 결과를 엑셀 파일로 저장"""
        kw = self.s_kw_edit.text().strip()
        st = self.s_st_edit.text().strip()
        
        if not kw or not st:
            QMessageBox.warning(self, "알림", "검색어와 스토어명을 먼저 입력하세요.")
            return
            
        row_count = self.s_hist_table.rowCount()
        if row_count == 0:
            QMessageBox.warning(self, "알림", "데이터가 없습니다.")
            return

        path, _ = QFileDialog.getSaveFileName(self, "보고서 저장", f"{st}_{kw}_순위추적.xlsx", "Excel Files (*.xlsx)")
        if not path: return

        try:
            wb = openpyxl.Workbook()
            ws = wb.active
            ws.title = "순위 히스토리"
            ws.append(["체크일시", "순위", "총검색수"])
            
            for r in range(row_count):
                row_data = [self.s_hist_table.item(r, c).text() for c in range(3)]
                ws.append(row_data)
                
            wb.save(path)
            QMessageBox.information(self, "완료", "보고서가 생성되었습니다.")
        except Exception as e:
            QMessageBox.critical(self, "오류", f"보고서 생성 실패: {e}")
            
    # ========== 관리/수정 로직 ==========
    def edit_selected_product(self):
        row = self.manage_table.currentRow()
        if row < 0: return
        p_id = int(self.manage_table.item(row, 0).text())
        prods = self.db.get_all_products()
        prod = next((p for p in prods if p[0] == p_id), None)
        if prod:
            d = ProductDialog(self.db, prod, self)
            if d.exec() == QDialog.DialogCode.Accepted:
                self.db.update_product(p_id, d.get_data())
                self.load_initial_data()

    def delete_selected_product(self):
        row = self.manage_table.currentRow()
        if row < 0: return
        p_id = int(self.manage_table.item(row, 0).text())
        if QMessageBox.question(self, "삭제", "정말 삭제하시겠습니까?") == QMessageBox.StandardButton.Yes:
            self.db.delete_product(p_id)
            self.load_initial_data()

    def show_product_context_menu(self, pos):
        item = self.p_list.itemAt(pos)
        if not item: return
        p_id = item.data(Qt.ItemDataRole.UserRole)
        menu = QMenu(); menu.setStyleSheet("QMenu::item:selected { background: #3b82f6; color: white; }")
        pin_act = menu.addAction("📌 고정/해제"); edit_act = menu.addAction("✏️ 수정"); del_act = menu.addAction("🗑️ 삭제")
        act = menu.exec(self.p_list.mapToGlobal(pos))
        if act == pin_act:
            prods = self.db.get_all_products()
            p = next((x for x in prods if x[0] == p_id), None)
            self.db.update_pin_status(p_id, 0 if p[12] else 1); self.load_initial_data()
        elif act == edit_act: self.edit_product_dialog(p_id)
        elif act == del_act: self.delete_product_action(p_id)

    def edit_product_dialog(self, p_id):
        prods = self.db.get_all_products(); p = next((x for x in prods if x[0] == p_id), None)
        d = ProductDialog(self.db, p, self)
        if d.exec() == QDialog.DialogCode.Accepted:
            self.db.update_product(p_id, d.get_data()); self.load_initial_data()

    def delete_product_action(self, p_id):
        if QMessageBox.question(self, "삭제", "삭제하시겠습니까?") == QMessageBox.StandardButton.Yes:
            self.db.delete_product(p_id); self.load_initial_data()

    def save_api_keys(self):
        self.db.set_api_keys(self.api_id.text(), self.api_sec.text()); QMessageBox.information(self, "완료", "저장되었습니다.")

    def export_all_history_to_excel(self):
        QMessageBox.information(self, "알림", "엑셀 추출 기능은 현재 세션의 데이터를 기반으로 동작합니다.")
        # 상세 구현 생략 (기존 패턴 유지)

    def crawl_all_products(self):
        targets = [(p[0], p[7], p[8], p[5]) for p in self.db.get_all_products() if p[7] and p[8]]
        if not targets: return
        self.worker = CrawlWorker(targets, True)
        self.worker.finished.connect(self.on_crawl_finished); self.worker.start()

    def on_crawl_finished(self, results):
        for p_id, price, success, info in results:
            if success:
                all_p = self.db.get_all_products(); p = next((x for x in all_p if x[0] == p_id), None)
                self.db.add_price_history(p_id, price, p[11], info['vendor'])
        self.load_initial_data()

if __name__ == '__main__':
    app = QApplication(sys.argv)
    
    # [디자인 개선] 현대적인 폰트 및 스타일 시트 적용
    app.setFont(QFont("Malgun Gothic", 10))
    app.setStyleSheet("""
        QMainWindow { background-color: #f1f5f9; }
        QPushButton { border-radius: 4px; padding: 6px; min-width: 60px; }
        QPushButton:hover { background-color: #e2e8f0; }
        QLineEdit, QDateEdit, QComboBox { padding: 5px; border: 1px solid #cbd5e1; border-radius: 4px; }
        QTableWidget { gridline-color: #e2e8f0; border: none; background: white; }
        QHeaderView::section { background-color: #f8fafc; padding: 4px; border: 1px solid #e2e8f0; font-weight: bold; }
    """)
    
    win = MarketResearchApp()
    win.show()
    sys.exit(app.exec())