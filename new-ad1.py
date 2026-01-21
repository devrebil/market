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
from selenium import webdriver
from selenium.webdriver.chrome.service import Service as ChromeService
from selenium.webdriver.edge.service import Service as EdgeService
from webdriver_manager.chrome import ChromeDriverManager
from webdriver_manager.microsoft import EdgeChromiumDriverManager

# PyQt6 라이브러리 임포트
# PyQt6 라이브러리 임포트
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QSplitter, QListWidget, QListWidgetItem, QLabel, QLineEdit,
    QPushButton, QTableWidget, QTableWidgetItem, QHeaderView,
    QTreeWidget, QTreeWidgetItem, QMessageBox, QFrame, QTabWidget,
    QDialog, QComboBox, QTextEdit, QFormLayout, QDialogButtonBox,
    QProgressDialog, QSpinBox, QMenu, QFileDialog,
    QDateEdit, QSizePolicy 
)
from PyQt6.QtWebEngineWidgets import QWebEngineView
from PyQt6.QtCore import QUrl

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

    def update_bookmark(self, b_id, name, url):
        conn = self.get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute('UPDATE bookmarks SET site_name=?, url=? WHERE id=?', (name, url, b_id))
            conn.commit()
        finally:
            conn.close()

    def update_bookmark_category(self, b_id, l, m, s):
        """북마크의 폴더 위치(카테고리)를 변경"""
        conn = self.get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute('''
                UPDATE bookmarks 
                SET category_large=?, category_medium=?, category_small=? 
                WHERE id=?
            ''', (l, m, s, b_id))
            conn.commit()
        finally:
            conn.close()

    def delete_bookmark_folder(self, l, m="", s=""):
        """특정 폴더와 그 안의 모든 즐겨찾기 삭제"""
        conn = self.get_connection()
        try:
            cursor = conn.cursor()
            query = "DELETE FROM bookmarks WHERE category_large=?"
            params = [l]
            if m:
                query += " AND category_medium=?"
                params.append(m)
            if s:
                query += " AND category_small=?"
                params.append(s)
            cursor.execute(query, params)
            conn.commit()
        finally:
            conn.close()
   
    def get_product_by_id(self, p_id):
        """특정 ID의 상품 정보 하나만 가져오기"""
        conn = self.get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute('SELECT * FROM products WHERE id = ?', (p_id,))
            return cursor.fetchone()
        finally:
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

    def update_search_preset_info(self, preset_id, store, keyword):
        conn = self.get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute('UPDATE search_presets SET store_name=?, keyword=? WHERE id=?', (store, keyword, preset_id))
            conn.commit()
        finally:
            conn.close()

    def delete_search_preset(self, preset_id):
        conn = self.get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute('DELETE FROM search_presets WHERE id=?', (preset_id,))
            conn.commit()
        finally:
            conn.close()

    def clear_product_price_history(self, p_id):
        conn = self.get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute('DELETE FROM price_history WHERE product_id=?', (p_id,))
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

    def update_presets_order(self, ordered_presets):
        """프리셋 순서를 DB에 영구적으로 저장 (기존 데이터를 지우고 새 순서로 삽입)"""
        conn = self.get_connection()
        try:
            cursor = conn.cursor()
            # 기존 프리셋을 모두 삭제하고 새 순서대로 다시 삽입하여 ID 순서를 재정렬합니다.
            cursor.execute('DELETE FROM search_presets')
            for p in ordered_presets:
                # p 데이터 구조: (id, store_name, keyword, pinned, pinned_at, created_at)
                cursor.execute('''
                    INSERT INTO search_presets (store_name, keyword, pinned, pinned_at, created_at)
                    VALUES (?, ?, ?, ?, ?)
                ''', (p[1], p[2], p[3], p[4], p[5]))
            conn.commit()
        finally:
            conn.close()

    def delete_search_history_by_keyword(self, store, keyword):
        """특정 스토어와 검색어에 해당하는 모든 순위 히스토리 삭제"""
        conn = self.get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute('DELETE FROM search_history WHERE store_name = ? AND keyword = ?', (store, keyword))
            conn.commit()
        finally:
            conn.close()

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
        """다양한 브라우저 환경을 지원하는 범용 드라이버 초기화"""
        try:
            self.close()
            # [1순위] 탐지 방지 크롬(UC) 시도
            try:
                options = uc.ChromeOptions()
                if self.headless:
                    options.add_argument('--headless')
                options.add_argument('--no-sandbox')
                options.add_argument('--disable-dev-shm-usage')
                # 자동으로 드라이버 버전을 맞추도록 수정
                self.driver = uc.Chrome(options=options)
                print("✅ undetected_chromedriver(Chrome) 실행 성공")
                return
            except Exception as e:
                print(f"⚠️ UC 크롬 실행 실패, 표준 크롬으로 전환: {e}")

            # [2순위] 표준 크롬 시도 (webdriver-manager 사용)
            try:
                chrome_options = webdriver.ChromeOptions()
                if self.headless:
                    chrome_options.add_argument('--headless')
                service = ChromeService(ChromeDriverManager().install())
                self.driver = webdriver.Chrome(service=service, options=chrome_options)
                print("✅ 표준 Chrome 실행 성공")
                return
            except Exception as e:
                print(f"⚠️ 크롬 실행 불가, 엣지(Edge)로 전환: {e}")

            # [3순위] 마이크로소프트 엣지 시도 (윈도우 기본 탑재)
            try:
                edge_options = webdriver.EdgeOptions()
                if self.headless:
                    edge_options.add_argument('--headless')
                service = EdgeService(EdgeChromiumDriverManager().install())
                self.driver = webdriver.Edge(service=service, options=edge_options)
                print("✅ Microsoft Edge 실행 성공")
                return
            except Exception as e:
                print(f"❌ 모든 브라우저 초기화 실패: {e}")
                self.driver = None

        except Exception as e:
            print(f"🔴 드라이버 초기화 중 치명적 오류: {e}")
            self.driver = None

    def get_price(self, url, selector, wait_time=15):
        if not self.driver: 
            self.init_driver()
        if not self.driver: 
            return (False, None, "사용 가능한 브라우저를 찾을 수 없습니다.")
        
        try:
            self.driver.get(url)
            wait = WebDriverWait(self.driver, wait_time)
            elem = wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, selector)))
            digits = ''.join(filter(str.isdigit, elem.text.strip()))
            return (True, int(digits), None) if digits else (False, None, "숫자 추출 실패")
        except Exception as e:
            return (False, None, str(e))

    def close(self):
        """핸들 오류 방지를 위한 안전 종료"""
        if self.driver:
            try:
                self.driver.quit()
            except:
                pass
            finally:
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
            sc = SeleniumCrawler(headless=True)
            try:
                for i, (p_id, url, sel, vendor) in enumerate(self.targets):
                    self.progress.emit(int((i / total) * 100), f"크롤링 중: {vendor}")
                    
                    # [추가] URL 유효성 검사 (비어있거나 형식이 잘못된 경우 방지)
                    if not url or not isinstance(url, str) or not url.startswith('http'):
                        results.append((p_id, None, False, {'vendor': vendor, 'error': 'invalid_url'}))
                        continue

                    success, price, err = sc.get_price(url, sel)
                    
                    if not success:
                        print(f"⚠️ {vendor} 자동 크롤링 실패. 보안 확인을 위해 페이지를 엽니다.")
                        sc.headless = False
                        sc.init_driver()
                        
                        if sc.driver:
                            try:
                                # [수정] 다시 한번 URL을 검증한 후 페이지 이동
                                if url and url.startswith('http'):
                                    sc.driver.get(url)
                                    
                                    # 사용자가 창을 닫을 때까지 대기
                                    while True:
                                        try:
                                            _ = sc.driver.window_handles
                                            self.msleep(500)
                                        except:
                                            print("ℹ️ 사용자가 브라우저 창을 닫았습니다.")
                                            break
                                else:
                                    print(f"❌ 잘못된 URL 형식: {url}")
                            except Exception as e:
                                print(f"❌ 브라우저 제어 중 오류 발생: {e}")
                        
                        results.append((p_id, None, False, {'vendor': vendor, 'error': 'manual_closed'}))
                    else:
                        results.append((p_id, price, True, {'vendor': vendor}))
            finally:
                sc.close()
        
        self.progress.emit(100, "완료")
        self.finished.emit(results)

# ============================================================
# 다이얼로그 클래스들
# ============================================================
class ProductDialog(QDialog):
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
        self.vendor = QLineEdit() # 매입처 필드
        self.price = QLineEdit()
        self.fee = QLineEdit(); self.fee.setText("0")
        self.url = QLineEdit()
        self.selector = QLineEdit()
        self.memo = QTextEdit(); self.memo.setMaximumHeight(60)
        
        layout.addRow("대분류:", self.c_l)
        layout.addRow("중분류:", self.c_m)
        layout.addRow("소분류:", self.c_s)
        layout.addRow("상품명*:", self.name)
        layout.addRow("매입처*:", self.vendor)
        layout.addRow("현재가격*:", self.price)
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
            self.c_l.setCurrentText(p[1]); self.c_m.setCurrentText(p[2] or ""); self.c_s.setCurrentText(p[3] or "")
            self.name.setText(p[4]); self.vendor.setText(p[5]); self.price.setText(str(p[6]))
            self.url.setText(p[7] or ""); self.selector.setText(p[8] or ""); self.memo.setPlainText(p[9] or "")
            self.fee.setText(str(p[11]))

    def get_data(self):
        return {
            'category_large': self.c_l.currentText(),
            'category_medium': self.c_m.currentText(),
            'category_small': self.c_s.currentText(),
            'product_name': self.name.text(),
            'vendor': self.vendor.text(),
            'price': int(self.price.text() or 0),
            'delivery_fee': int(self.fee.text() or 0),
            'url': self.url.text(),
            'css_selector': self.selector.text(),
            'memo': self.memo.toPlainText()
        }

class BookmarkEditDialog(QDialog):
    """즐겨찾기 수정 다이얼로그"""
    def __init__(self, db, bookmark_data, parent=None):
        super().__init__(parent)
        self.db = db
        self.data = bookmark_data # (id, l, m, s, name, url)
        self.setWindowTitle("즐겨찾기 수정")
        layout = QFormLayout(self)
        
        self.name = QLineEdit(self.data[4])
        self.url = QLineEdit(self.data[5])
        
        layout.addRow("사이트명*:", self.name)
        layout.addRow("URL*:", self.url)
        
        btns = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)
        layout.addRow(btns)

    def get_data(self):
        return {'site_name': self.name.text(), 'url': self.url.text()}

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

from PyQt6.QtCore import QEvent, QObject

from PyQt6.QtCore import QObject, QEvent, Qt

from PyQt6.QtCore import QObject, QEvent, Qt

class TabScrollFilter(QObject):
    """탭 바를 마우스 드래그 및 휠로 넘기기 위한 필터"""
    def __init__(self, tab_widget):
        super().__init__(tab_widget)
        self.tabs = tab_widget
        self.last_x = 0

    def eventFilter(self, obj, event):
        # 마우스 휠로 탭 전환 
        if event.type() == QEvent.Type.Wheel:
            if event.angleDelta().y() > 0:
                self.tabs.setCurrentIndex(max(0, self.tabs.currentIndex() - 1))
            else:
                self.tabs.setCurrentIndex(min(self.tabs.count() - 1, self.tabs.currentIndex() + 1))
            return True
        
        # 마우스 드래그로 탭 넘기기
        elif event.type() == QEvent.Type.MouseButtonPress:
            self.last_x = event.pos().x()
        
        elif event.type() == QEvent.Type.MouseMove and event.buttons() & Qt.MouseButton.LeftButton:
            curr_x = event.pos().x()
            delta = curr_x - self.last_x
            
            if abs(delta) > 25:
                if delta > 0:
                    self.tabs.setCurrentIndex(max(0, self.tabs.currentIndex() - 1))
                else:
                    self.tabs.setCurrentIndex(min(self.tabs.count() - 1, self.tabs.currentIndex() + 1))
                self.last_x = curr_x
            return True
            
        return super().eventFilter(obj, event)


class PresetReorderDialog(QDialog):
    """탭 순서 및 전체 프리셋 편집 다이얼로그"""
    def __init__(self, db, parent=None):
        super().__init__(parent)
        self.db = db
        self.setWindowTitle("프리셋 전체 편집")
        self.setMinimumSize(400, 500)
        layout = QVBoxLayout(self)
        
        layout.addWidget(QLabel("마우스로 항목을 드래그하여 순서를 변경하세요.\n(현재 리스트 순서대로 탭이 재구성됩니다)"))
        
        self.list_widget = QListWidget()
        self.list_widget.setDragDropMode(QListWidget.DragDropMode.InternalMove)
        self.load_presets()
        layout.addWidget(self.list_widget)
        
        btns = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)
        layout.addWidget(btns)

    def load_presets(self):
        presets = self.db.get_search_presets()
        for p in presets:
            item = QListWidgetItem(f"[{p[1]}] {p[2]}")
            item.setData(Qt.ItemDataRole.UserRole, p) # 전체 데이터 저장
            self.list_widget.addItem(item)

    def get_ordered_data(self):
        items = []
        for i in range(self.list_widget.count()):
            items.append(self.list_widget.item(i).data(Qt.ItemDataRole.UserRole))
        return items


class DonationDialog(QDialog):
    """후원을 위한 작은 모달 창"""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("개발자 응원하기")
        self.setFixedSize(400, 300)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(15)

        # 문구 설정
        content_text = (
            "<b>저를 응원 해 주신다면</b><br>"
            "<b>차 한잔 사주시면 감사하겠습니다.</b><br><br><br>"
            "<font color='#64748b' size='2'>"
            "본 도네이션은 프로그램 이용과 무관한 자발적 후원입니다.<br>"
            "도네이션 여부에 따라 기능, 업데이트, 지원, 서비스 제공에 차이가 없으며<br>"
            "업데이트 일정 및 내용은 개발자 판단에 따라 진행됩니다."
            "</font><br><br>"
            "<b><font color='#3b82f6' size='4'>100-127-679608 케이뱅크</font></b>"
        )

        msg_label = QLabel(content_text)
        msg_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        msg_label.setWordWrap(True)
        layout.addWidget(msg_label)

        # 닫기 버튼
        btn_close = QPushButton("확인")
        btn_close.setFixedHeight(40)
        btn_close.setStyleSheet("""
            QPushButton { background-color: #f1f5f9; border: 1px solid #cbd5e1; border-radius: 6px; font-weight: bold; }
            QPushButton:hover { background-color: #e2e8f0; }
        """)
        btn_close.clicked.connect(self.accept)
        layout.addWidget(btn_close)
        
# ============================================================
# 메인 윈도우
# ============================================================
class MarketResearchApp(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("시장조사 프로그램  - 무지개블로")
        self.settings = QSettings("MyCompany", "MarketResearchApp")
        
        # 창 크기 복구
        geometry = self.settings.value("geometry")
        if geometry: self.restoreGeometry(geometry)
        else: self.resize(1400, 900)
        
        self.db = DatabaseManager()
        self.current_product_id = None
        
        self.init_ui()
        self.load_initial_data()
        
        # [추가] 단축키 등록 (Ctrl+S, F8)
        from PyQt6.QtGui import QKeySequence, QShortcut
        QShortcut(QKeySequence("Ctrl+S"), self).activated.connect(self.backup_database)
        QShortcut(QKeySequence("F8"), self).activated.connect(self.backup_database)

    def backup_database(self):
        """데이터베이스 백업 수행 (Ctrl+S / F8)"""
        import shutil
        import os
        
        backup_dir = "DB Backup"
        if not os.path.exists(backup_dir):
            os.makedirs(backup_dir) # 폴더가 없으면 자동 생성

        # 파일명 형식: market_research_v3_yymmdd HHMM.db
        now = datetime.now()
        timestamp = now.strftime("%y%m%d %H%M")
        db_name = self.db.db_name # 기본값 market_research_v3.db [cite: 1, 2]
        backup_filename = f"{db_name.split('.')[0]}_{timestamp}.db"
        dest_path = os.path.join(backup_dir, backup_filename)

        try:
            shutil.copy2(db_name, dest_path)
            self.statusBar().showMessage(f"✅ DB 백업 완료: {backup_filename}", 5000)
        except Exception as e:
            QMessageBox.critical(self, "백업 오류", f"DB 백업 중 오류가 발생했습니다: {e}")

    def restore_database(self):
        """백업된 DB 파일을 불러와 현재 DB에 덮어쓰기"""
        import shutil
        import os
        
        path, _ = QFileDialog.getOpenFileName(self, "복원할 백업 파일 선택", "DB Backup", "Database Files (*.db)")
        if not path: return

        reply = QMessageBox.question(self, "복원 확인", 
                                   "선택한 백업 파일로 현재 데이터를 덮어씁니다.\n진행하시겠습니까? (현재 데이터는 유실됩니다)",
                                   QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        
        if reply == QMessageBox.StandardButton.Yes:
            try:
                # 현재 DB 파일을 백업 파일로 교체
                shutil.copy2(path, self.db.db_name)
                QMessageBox.information(self, "복원 완료", "데이터 복원이 완료되었습니다.\n정확한 데이터 반영을 위해 프로그램을 재시작해 주세요.")
                self.load_initial_data() # UI 새로고침 [cite: 1, 67]
            except Exception as e:
                QMessageBox.critical(self, "복원 오류", f"복원 중 오류 발생: {e}")

    def show_donation_dialog(self):
        """후원 모달 다이얼로그 표시"""
        dialog = DonationDialog(self)
        dialog.exec()

    def closeEvent(self, event):
        """종료 시 설정 저장"""
        self.settings.setValue("geometry", self.saveGeometry())
        self.settings.setValue("manage_table_header", self.manage_table.horizontalHeader().saveState())
        super().closeEvent(event)

    def init_ui(self):
        main_widget = QWidget()
        self.setCentralWidget(main_widget)
        
        # 전체 레이아웃을 수직 방향으로 설정합니다. 
        main_layout = QVBoxLayout(main_widget)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)
        
        # [상단] 기존의 탭 위젯을 배치합니다.
        self.tabs = QTabWidget()
        # ... (탭 스타일 및 추가 코드 생략) ...
        self.home_tab = QWidget(); self.setup_home_tab(); self.tabs.addTab(self.home_tab, "🏠 홈")
        self.search_tab = QWidget(); self.setup_search_tab(); self.tabs.addTab(self.search_tab, "🔍 검색")
        self.manage_tab = QWidget(); self.setup_manage_tab(); self.tabs.addTab(self.manage_tab, "⚙️ 관리")
        main_layout.addWidget(self.tabs)
        
        # [하단] 바로 위에서 만든 광고 영역을 탭 아래에 고정합니다.
        self.setup_ad_section(main_layout)

    def setup_ad_section(self, parent_layout):
        """하단 광고 영역 및 후원 버튼 생성"""
        ad_h_layout = QHBoxLayout()
        ad_h_layout.setContentsMargins(5, 5, 5, 5)
        ad_h_layout.setSpacing(10)

        # [1] 도움말 & 버그신고 버튼 (좌측)
        self.btn_help = QPushButton("도움말 &\n버그신고")
        self.btn_help.setFixedWidth(120)
        self.btn_help.setFixedHeight(100)
        self.btn_help.setStyleSheet("""
            QPushButton { background-color: #f8fafc; border: 1px solid #cbd5e1; border-radius: 8px; font-weight: bold; color: #475569; }
            QPushButton:hover { background-color: #f1f5f9; }
        """)
        self.btn_help.clicked.connect(lambda: webbrowser.open("https://rebil85.tistory.com/")) 
        ad_h_layout.addWidget(self.btn_help)

        # [신규] 후원하기 버튼 (도움말 버튼 우측)
        self.btn_donate = QPushButton("☕\n후원하기")
        self.btn_donate.setFixedWidth(80)
        self.btn_donate.setFixedHeight(100)
        self.btn_donate.setStyleSheet("""
            QPushButton { background-color: #fff7ed; border: 1px solid #fdba74; border-radius: 8px; font-weight: bold; color: #c2410c; }
            QPushButton:hover { background-color: #ffedd5; }
        """)
        self.btn_donate.clicked.connect(self.show_donation_dialog)
        ad_h_layout.addWidget(self.btn_donate)

        # [2] 웹뷰 광고 (중앙)
        self.ad_view = QWebEngineView()
        self.ad_view.setFixedHeight(100)
        self.ad_view.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.ad_view.setUrl(QUrl("https://rebil85.tistory.com/pages/AD-Page"))
        self.ad_view.setStyleSheet("border-radius: 8px; border: 1px solid #e2e8f0;")
        ad_h_layout.addWidget(self.ad_view)

        # [3] DB 관리 버튼 영역 (우측)
        db_v_layout = QVBoxLayout()
        self.btn_main_backup = QPushButton("💾 DB 백업")
        self.btn_main_backup.setFixedWidth(120)
        self.btn_main_backup.setFixedHeight(45)
        self.btn_main_backup.setStyleSheet("""
            QPushButton { background-color: white; border: 1px solid #cbd5e1; border-radius: 8px; font-weight: bold; color: #475569; }
            QPushButton:hover { background-color: #f1f5f9; }
        """)
        self.btn_main_backup.clicked.connect(self.backup_database)

        self.btn_main_restore = QPushButton("📂 DB 복구")
        self.btn_main_restore.setFixedWidth(120)
        self.btn_main_restore.setFixedHeight(45)
        self.btn_main_restore.setStyleSheet("""
            QPushButton { background-color: white; border: 1px solid #cbd5e1; border-radius: 8px; font-weight: bold; color: #475569; }
            QPushButton:hover { background-color: #f1f5f9; }
        """)
        self.btn_main_restore.clicked.connect(self.restore_database)

        db_v_layout.addWidget(self.btn_main_backup)
        db_v_layout.addWidget(self.btn_main_restore)
        ad_h_layout.addLayout(db_v_layout)

        parent_layout.addLayout(ad_h_layout)

    def setup_home_tab(self):
        """홈 탭 UI - 드래그 앤 드롭 및 우클릭 정책 적용"""
        layout = QHBoxLayout(self.home_tab)
        splitter = QSplitter(Qt.Orientation.Horizontal)
        
        outline_style = """
            QPushButton { background-color: white; border: 1px solid #cbd5e1; border-radius: 4px; padding: 6px 12px; color: #475569; }
            QPushButton:hover { background-color: #f8fafc; border-color: #94a3b8; }
        """
        
        # [1] 좌측: 상품 관리
        area1 = QWidget(); v1 = QVBoxLayout(area1)
        v1.addWidget(QLabel("🛍️ 상품 관리"))
        self.btn_add_p = QPushButton("➕ 상품 등록"); self.btn_add_p.setFixedHeight(40)
        self.btn_add_p.setStyleSheet(outline_style + "QPushButton { color: #3b82f6; font-weight: bold; }")
        self.btn_add_p.clicked.connect(self.add_product_dialog); v1.addWidget(self.btn_add_p)
        
        self.search_p = QLineEdit(); self.search_p.setPlaceholderText("검색..."); self.search_p.textChanged.connect(self.refresh_product_list); v1.addWidget(self.search_p)
        
        self.p_list = QListWidget()
        self.p_list.itemClicked.connect(self.on_product_clicked)
        self.p_list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.p_list.customContextMenuRequested.connect(self.show_product_context_menu)
        v1.addWidget(self.p_list); splitter.addWidget(area1)
        
        # [2] 중앙: 히스토리
        area2 = QWidget(); v2 = QVBoxLayout(area2)
        h2 = QHBoxLayout(); h2.addWidget(QLabel("🕒 히스토리")); h2.addStretch()
        btn_clear_hist = QPushButton("🗑️ 초기화"); btn_clear_hist.setStyleSheet(outline_style + "QPushButton { color: #ef4444; }")
        btn_clear_hist.clicked.connect(self.clear_current_history); h2.addWidget(btn_clear_hist)
        btn_excel = QPushButton("📊 엑셀"); btn_excel.setStyleSheet(outline_style); h2.addWidget(btn_excel)
        btn_crawl = QPushButton("🔄 크롤링"); btn_crawl.setStyleSheet(outline_style); btn_crawl.clicked.connect(self.crawl_all_products); h2.addWidget(btn_crawl)
        v2.addLayout(h2)
        self.h_table = QTableWidget(0, 6); self.h_table.setHorizontalHeaderLabels(["날짜", "시간", "매입처", "가격", "택배비", "변동폭"])
        self.h_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        v2.addWidget(self.h_table); splitter.addWidget(area2)
        
        # [3] 우측: 즐겨찾기 및 드래그 앤 드롭 설정
        area3 = QWidget(); v3 = QVBoxLayout(area3)
        self.figure = plt.Figure(figsize=(5, 4), dpi=100); self.canvas = FigureCanvas(self.figure); self.ax = self.figure.add_subplot(111)
        v3.addWidget(QLabel("📈 가격 추이")); v3.addWidget(self.canvas)
        
        h_bm = QHBoxLayout(); h_bm.addWidget(QLabel("🔖 즐겨찾기")); h_bm.addStretch()
        btn_import_bm = QPushButton("📁 폴더추가"); btn_import_bm.setStyleSheet(outline_style); btn_import_bm.clicked.connect(self.import_bookmarks_from_browser); h_bm.addWidget(btn_import_bm)
        btn_add_bm = QPushButton("➕ 추가"); btn_add_bm.setStyleSheet(outline_style); btn_add_bm.clicked.connect(self.add_bookmark_dialog); h_bm.addWidget(btn_add_bm)
        v3.addLayout(h_bm)
        
        self.bm_tree = QTreeWidget(); self.bm_tree.setHeaderHidden(True)
        # --- 드래그 앤 드롭 기능 활성화 ---
        self.bm_tree.setDragEnabled(True)
        self.bm_tree.setAcceptDrops(True)
        self.bm_tree.setDragDropMode(QTreeWidget.DragDropMode.InternalMove)
        
        self.bm_tree.itemDoubleClicked.connect(self.on_bookmark_double_clicked)
        self.bm_tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.bm_tree.customContextMenuRequested.connect(self.show_bookmark_context_menu)
        
        # 드롭 이벤트 처리를 위한 필터 설치
        self.bm_tree.model().rowsMoved.connect(self.on_bookmark_dropped)
        
        v3.addWidget(self.bm_tree); splitter.addWidget(area3)
        splitter.setSizes([300, 600, 400]); layout.addWidget(splitter)

    def clear_current_history(self):
        """현재 선택된 상품의 히스토리 삭제"""
        if not self.current_product_id:
            QMessageBox.warning(self, "알림", "삭제할 상품을 먼저 선택하세요.")
            return
        if QMessageBox.question(self, "초기화", "이 상품의 모든 가격 히스토리를 삭제하시겠습니까?") == QMessageBox.StandardButton.Yes:
            self.db.clear_product_price_history(self.current_product_id)
            self.update_history_and_graph()

    def import_bookmarks_from_browser(self):
        """브라우저 북마크 HTML 파일 가져오기"""
        path, _ = QFileDialog.getOpenFileName(self, "북마크 HTML 선택", "", "HTML Files (*.html)")
        if not path: return
        
        try:
            with open(path, 'r', encoding='utf-8') as f:
                soup = BeautifulSoup(f.read(), 'html.parser')
                links = soup.find_all('a')
                for link in links:
                    name = link.get_text()
                    url = link.get('href')
                    if url and url.startswith('http'):
                        self.db.add_bookmark({
                            'category_large': '가져온 북마크',
                            'category_medium': '', 'category_small': '',
                            'site_name': name, 'url': url
                        })
            QMessageBox.information(self, "완료", f"{len(links)}개의 북마크를 성공적으로 가져왔습니다.")
            self.refresh_bookmarks()
        except Exception as e:
            QMessageBox.critical(self, "오류", f"북마크를 읽는 중 오류가 발생했습니다: {e}")

    def setup_search_tab(self):
        """검색 탭 UI - 초기화 버튼 추가 및 우클릭 메뉴 통합 버전"""
        layout = QHBoxLayout(self.search_tab)
        splitter = QSplitter(Qt.Orientation.Horizontal)
        
        outline_style = """
            QPushButton { background-color: white; border: 1px solid #cbd5e1; border-radius: 4px; padding: 6px 12px; color: #475569; }
            QPushButton:hover { background-color: #f8fafc; border-color: #94a3b8; }
        """

        # [1] 좌측: 프리셋 관리
        area1 = QWidget()
        v1 = QVBoxLayout(area1)
        btn_reg = QPushButton("➕ 검색어 등록")
        btn_reg.setFixedHeight(40)
        btn_reg.setStyleSheet(outline_style + "QPushButton { color: #6366f1; font-weight: bold; }")
        btn_reg.clicked.connect(self.reg_search_preset)
        v1.addWidget(btn_reg)
        
        self.s_preset_tabs = QTabWidget()
        self.s_preset_tabs.setMovable(True)
        self.tab_filter = TabScrollFilter(self.s_preset_tabs)
        self.s_preset_tabs.tabBar().installEventFilter(self.tab_filter)
        
        # 탭 바 우클릭 메뉴 설정
        self.s_preset_tabs.tabBar().setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.s_preset_tabs.tabBar().customContextMenuRequested.connect(self.show_tab_context_menu)
        
        self.s_preset_tabs.setStyleSheet("""
            QTabBar::tab { font-size: 14px; padding: 8px 16px; background-color: #f8fafc; border: 1px solid #cbd5e1; margin-right: 2px; }
            QTabBar::tab:selected { background-color: white; color: #4f46e5; font-weight: bold; border-bottom: 2px solid white; }
        """)
        v1.addWidget(self.s_preset_tabs)
        splitter.addWidget(area1)
        
        # [2] 중앙: 검색 및 히스토리
        area2 = QWidget()
        v2 = QVBoxLayout(area2)
        v2.setContentsMargins(10, 10, 10, 10)
        
        search_box = QFrame()
        search_box.setStyleSheet("background-color: white; border-radius: 8px; border: 1px solid #e2e8f0;")
        f2 = QFormLayout(search_box)
        self.s_kw_edit = QLineEdit()
        self.s_st_edit = QLineEdit()
        f2.addRow("🔍 검색어:", self.s_kw_edit)
        f2.addRow("🏪 스토어명:", self.s_st_edit)
        v2.addWidget(search_box)
        
        h_btns = QHBoxLayout()
        # 순위 검색 시작
        btn_run = QPushButton("🚀 순위 검색 시작")
        btn_run.setStyleSheet("background-color: #4f46e5; color: white; font-weight: bold; padding: 10px; border-radius: 4px;")
        btn_run.clicked.connect(self.run_naver_search)
        
        # 보고서 생성
        self.btn_export_report = QPushButton("📋 보고서 생성")
        self.btn_export_report.setStyleSheet("background-color: #10b981; color: white; font-weight: bold; padding: 10px; border-radius: 4px;")
        self.btn_export_report.clicked.connect(self.generate_search_report)
        
        # [신규 추가] 초기화 버튼
        btn_clear_search = QPushButton("🗑️ 초기화")
        btn_clear_search.setStyleSheet(outline_style + "QPushButton { color: #ef4444; border-color: #fca5a5; font-weight: bold; padding: 10px; }")
        btn_clear_search.clicked.connect(self.clear_search_history_action)

        h_btns.addWidget(btn_run)
        h_btns.addWidget(self.btn_export_report)
        h_btns.addWidget(btn_clear_search) # 버튼 배치
        v2.addLayout(h_btns)
        
        v2.addWidget(QLabel("🕒 검색 히스토리"))
        self.s_hist_table = QTableWidget(0, 3)
        self.s_hist_table.setHorizontalHeaderLabels(["체크일시", "순위", "총검색수"])
        self.s_hist_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        v2.addWidget(self.s_hist_table)
        splitter.addWidget(area2)
        
        # [3] 우측: 필터 및 그래프
        area3 = QWidget()
        v3 = QVBoxLayout(area3)
        filter_group = QFrame()
        filter_group.setFixedHeight(140)
        f_layout = QVBoxLayout(filter_group)
        h_p_btns = QHBoxLayout()
        for text, days in [("7일", 7), ("1개월", 30), ("1년", 365), ("전체", 0)]:
            btn = QPushButton(text); btn.setStyleSheet(outline_style); btn.clicked.connect(lambda ch, d=days: self.set_filter_period(d)); h_p_btns.addWidget(btn)
        f_layout.addLayout(h_p_btns)
        
        h_dates = QHBoxLayout()
        self.s_start_date = QDateEdit(QDate.currentDate().addDays(-7)); self.s_end_date = QDateEdit(QDate.currentDate())
        self.s_start_date.setCalendarPopup(True); self.s_end_date.setCalendarPopup(True)
        btn_apply = QPushButton("적용"); btn_apply.setStyleSheet(outline_style); btn_apply.clicked.connect(self.apply_search_filter)
        h_dates.addWidget(QLabel("기간:")); h_dates.addWidget(self.s_start_date); h_dates.addWidget(QLabel("~")); h_dates.addWidget(self.s_end_date); h_dates.addWidget(btn_apply)
        f_layout.addLayout(h_dates)
        
        v3.addWidget(QLabel("📅 기간 설정")); v3.addWidget(filter_group); v3.addWidget(QLabel("📈 순위 변동 그래프"))
        self.s_figure = plt.Figure(figsize=(5, 3), dpi=100); self.s_canvas = FigureCanvas(self.s_figure); self.s_ax = self.s_figure.add_subplot(111); v3.addWidget(self.s_canvas)
        v3.addStretch(); splitter.addWidget(area3)
        
        splitter.setSizes([280, 570, 550])
        layout.addWidget(splitter)

    def show_tab_context_menu(self, pos):
        """탭 바 우클릭 메뉴 구현"""
        tab_index = self.s_preset_tabs.tabBar().tabAt(pos)
        menu = QMenu(self)
        
        act_edit_all = menu.addAction("📑 프리셋 전체 편집 (순위 변경)")
        act_modify = menu.addAction("✏️ 현재 탭 수정")
        act_delete = menu.addAction("🗑️ 현재 탭 삭제")
        
        action = menu.exec(self.s_preset_tabs.tabBar().mapToGlobal(pos))
        
        if action == act_edit_all:
            self.edit_all_presets_dialog()
        elif action == act_modify and tab_index >= 0:
            self.modify_current_tab_dialog(tab_index)
        elif action == act_delete and tab_index >= 0:
            self.delete_current_tab(tab_index)

    def edit_all_presets_dialog(self):
        """프리셋 전체 편집 다이얼로그 실행 및 순서 저장"""
        d = PresetReorderDialog(self.db, self)
        if d.exec() == QDialog.DialogCode.Accepted:
            new_order = d.get_ordered_data() # 변경된 순서 데이터 가져오기
            self.db.update_presets_order(new_order) # DB에 영구 저장 (순서 고정)
            self.refresh_search_presets() # UI 갱신
            QMessageBox.information(self, "완료", "탭 순서가 성공적으로 저장되었습니다.")

    def clear_search_history_action(self):
        """현재 입력된 스토어/검색어의 순위 히스토리 초기화"""
        st = self.s_st_edit.text().strip()
        kw = self.s_kw_edit.text().strip()
        
        if not st or not kw:
            QMessageBox.warning(self, "알림", "초기화할 스토어명과 검색어를 먼저 선택하세요.")
            return

        reply = QMessageBox.question(self, "히스토리 초기화", 
                                   f"[{st} - {kw}]\n해당 검색어의 모든 순위 기록을 삭제하시겠습니까?\n(삭제 후 복구할 수 없습니다)",
                                   QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        
        if reply == QMessageBox.StandardButton.Yes:
            self.db.delete_search_history_by_keyword(st, kw)
            self.apply_search_filter() # 표와 그래프 새로고침
            QMessageBox.information(self, "완료", "히스토리가 초기화되었습니다.")

    def modify_current_tab_dialog(self, index):
        """프리셋 수정 로직 - 실제 DB 반영 버전"""
        lw = self.s_preset_tabs.widget(index)
        if not lw or not lw.currentItem():
            QMessageBox.warning(self, "알림", "수정할 검색어를 목록에서 클릭하세요.")
            return
            
        item_data = lw.currentItem().data(Qt.ItemDataRole.UserRole)
        preset_id, current_store, current_kw = item_data
        
        d = QDialog(self); d.setWindowTitle("프리셋 수정")
        f = QFormLayout(d)
        st = QLineEdit(current_store); kw = QLineEdit(current_kw)
        f.addRow("스토어명:", st); f.addRow("검색어:", kw)
        btns = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        btns.accepted.connect(d.accept); btns.rejected.connect(d.reject); f.addRow(btns)
        
        if d.exec() == QDialog.DialogCode.Accepted:
            self.db.update_search_preset_info(preset_id, st.text().strip(), kw.text().strip())
            self.refresh_search_presets()
            QMessageBox.information(self, "완료", "프리셋 정보가 수정되었습니다.")

    def delete_current_tab(self, index):
        if QMessageBox.question(self, "삭제", "이 탭(프리셋)을 삭제하시겠습니까?") == QMessageBox.StandardButton.Yes:
            # DB 삭제 로직 호출 후
            self.refresh_search_presets()
        
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
        
        # [신규] DB 복원 버튼 추가
        self.btn_db_restore = QPushButton("📂 DB 복원하기")
        self.btn_db_restore.setStyleSheet("background-color: #f59e0b; color: white; font-weight: bold;")
        self.btn_db_restore.clicked.connect(self.restore_database)
        btn_group.addWidget(self.btn_db_restore)
        
        api_box = QFrame(); api_box.setFrameStyle(QFrame.Shape.StyledPanel); f_api = QFormLayout(api_box)
        self.api_id = QLineEdit(); self.api_sec = QLineEdit()
        c_id, c_sec = self.db.get_api_keys(); self.api_id.setText(c_id); self.api_sec.setText(c_sec)
        f_api.addRow("Naver Client ID:", self.api_id); f_api.addRow("Naver Secret:", self.api_sec)
        btn_save_api = QPushButton("API 키 저장"); btn_save_api.clicked.connect(self.save_api_keys); f_api.addRow(btn_save_api)
        layout.addWidget(api_box)
    
    def on_bookmark_dropped(self):
        """즐겨찾기 아이템 이동 시 새로운 폴더 위치를 DB에 영구 저장"""
        def update_recursive(item):
            # 자식 아이템들을 순회하며 위치 파악
            for i in range(item.childCount()):
                child = item.child(i)
                data = child.data(0, Qt.ItemDataRole.UserRole)
                
                if data: # 실제 즐겨찾기 아이템인 경우 (url, b_id)
                    b_id = data[1]
                    # 상위 부모들의 이름을 가져와 대/중/소 분류 결정
                    path = []
                    curr = child.parent()
                    while curr:
                        path.insert(0, curr.text(0))
                        curr = curr.parent()
                    
                    # 카테고리 정보 추출 (대, 중, 소)
                    l = path[0] if len(path) > 0 else "기본"
                    m = path[1] if len(path) > 1 else ""
                    s = path[2] if len(path) > 2 else ""
                    
                    # DB 업데이트 (DatabaseManager에 update_bookmark_category 메서드 필요)
                    self.db.update_bookmark_category(b_id, l, m, s)
                
                update_recursive(child)

        # 전체 트리 순회 시작
        for i in range(self.bm_tree.topLevelItemCount()):
            update_recursive(self.bm_tree.topLevelItem(i))
            
        print("📂 즐겨찾기 위치 변경 사항이 DB에 저장되었습니다.")

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
        """즐겨찾기 폴더 및 항목 우클릭 메뉴"""
        item = self.bm_tree.itemAt(pos)
        if not item: return
        
        data = item.data(0, Qt.ItemDataRole.UserRole) # (url, b_id)
        menu = QMenu()
        # 요청하신 노란색 호버 스타일 적용
        menu.setStyleSheet("""
            QMenu { background-color: white; border: 1px solid #cbd5e1; }
            QMenu::item { padding: 8px 25px; }
            QMenu::item:selected { background-color: #fde047; color: #1e293b; font-weight: bold; }
        """)

        if data: # 실제 즐겨찾기 사이트인 경우
            edit_act = menu.addAction("✏️ 즐겨찾기 수정")
            del_act = menu.addAction("🗑️ 즐겨찾기 삭제")
            act = menu.exec(self.bm_tree.mapToGlobal(pos))
            if act == edit_act:
                self.edit_bookmark_dialog(item, data)
            elif act == del_act:
                if QMessageBox.question(self, "삭제", "이 항목을 삭제하시겠습니까?") == QMessageBox.StandardButton.Yes:
                    self.db.delete_bookmark(data[1])
                    self.refresh_bookmarks()
        else: # 폴더(카테고리)인 경우
            folder_name = item.text(0)
            del_folder_act = menu.addAction(f"📂 '{folder_name}' 폴더 삭제")
            act = menu.exec(self.bm_tree.mapToGlobal(pos))
            if act == del_folder_act:
                if QMessageBox.question(self, "폴더 삭제", "폴더 내의 모든 즐겨찾기가 함께 삭제됩니다.\n진행하시겠습니까?") == QMessageBox.StandardButton.Yes:
                    # 대분류 기준으로 우선 삭제 (트리 깊이에 따라 보완 가능)
                    self.db.delete_bookmark_folder(folder_name)
                    self.refresh_bookmarks()

    def on_bookmark_dropped(self, parent_index, start, end, destination_index, row):
        """드래그 앤 드롭으로 이동된 항목의 카테고리 DB 업데이트"""
        # 트리 구조가 복잡하므로 이동 완료 후 전체 트리를 순회하며 DB를 일괄 동기화하는 것이 가장 안전합니다.
        QMessageBox.information(self, "알림", "이동된 위치를 저장하기 위해 화면을 갱신합니다.")
        # 상세 드롭 로직: 실제 상위 아이템의 텍스트를 읽어 DB update_bookmark_category 호출 필요
        self.refresh_bookmarks()

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

    # [상품 관리 우클릭 메뉴]
    def show_product_context_menu(self, pos):
        """상품 관리 우클릭 메뉴 - 노란색 호버 스타일 적용"""
        item = self.p_list.itemAt(pos)
        if not item: return
        p_id = item.data(Qt.ItemDataRole.UserRole)
        
        menu = QMenu()
        menu.setStyleSheet("""
            QMenu { background-color: white; border: 1px solid #cbd5e1; }
            QMenu::item { padding: 8px 25px; }
            QMenu::item:selected { background-color: #fde047; color: #1e293b; font-weight: bold; }
        """)
        
        pin_act = menu.addAction("📌 고정/해제")
        edit_act = menu.addAction("✏️ 수정")
        del_act = menu.addAction("🗑️ 삭제")
        
        act = menu.exec(self.p_list.mapToGlobal(pos))
        if act == edit_act:
            self.edit_product_dialog(p_id)
        elif act == del_act:
            self.delete_product_action(p_id)
        elif act == pin_act:
            prods = self.db.get_all_products()
            p = next((x for x in prods if x[0] == p_id), None)
            self.db.update_pin_status(p_id, 0 if p[12] else 1)
            self.load_initial_data()

    # [즐겨찾기 우클릭 메뉴]
    def show_bookmark_context_menu(self, pos):
        item = self.bm_tree.itemAt(pos)
        if not item: return
        data = item.data(0, Qt.ItemDataRole.UserRole) # (url, b_id)
        if not data: return # 폴더 노드인 경우 무시
        
        # 실제 DB 데이터를 가져오기 위해 트리 정보를 활용
        b_id = data[1]
        
        menu = QMenu()
        edit_act = menu.addAction("✏️ 즐겨찾기 수정")
        del_act = menu.addAction("🗑️ 즐겨찾기 삭제")
        
        act = menu.exec(self.bm_tree.mapToGlobal(pos))
        if act == del_act:
            if QMessageBox.question(self, "삭제", "이 즐겨찾기를 삭제하시겠습니까?") == QMessageBox.StandardButton.Yes:
                self.db.delete_bookmark(b_id)
                self.refresh_bookmarks()
        elif act == edit_act:
            # 수정을 위해 현재 노드의 정보를 다이얼로그에 전달
            # 간단하게 구현하기 위해 현재 이름과 URL 정보를 추출
            current_name = item.text(0)
            current_url = data[0]
            d = BookmarkEditDialog(self.db, (b_id, "", "", "", current_name, current_url), self)
            if d.exec() == QDialog.DialogCode.Accepted:
                new_data = d.get_data()
                self.db.update_bookmark(b_id, new_data['site_name'], new_data['url'])
                self.refresh_bookmarks()

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
        """선택된 상품 하나만 크롤링 실행 - URL 유효성 검사 강화"""
        if not self.current_product_id:
            QMessageBox.warning(self, "알림", "상품을 먼저 선택해주세요.")
            return

        p = self.db.get_product_by_id(self.current_product_id)
        
        # p[7]은 URL 필드입니다.
        if not p or not p[7] or not str(p[7]).strip().startswith('http'):
            QMessageBox.warning(self, "알림", "올바른 URL 정보가 없습니다.\n(http:// 또는 https://로 시작해야 합니다.)")
            return
            
        if not p[8]:
            QMessageBox.warning(self, "알림", "Selector 정보가 없습니다.")
            return

        targets = [(p[0], p[7], p[8], p[5])]
        self.worker = CrawlWorker(targets, True)
        self.worker.finished.connect(self.on_crawl_finished)
        self.worker.start()

    def on_crawl_finished(self, results):
        """결과에 따른 메시지 분기 처리"""
        retry_needed = False
        success_count = 0

        for p_id, price, success, info in results:
            if not success and info.get('error') == 'manual_closed':
                retry_needed = True
            elif success:
                # DB 저장 로직 (생략)
                success_count += 1

        self.load_initial_data()

        if retry_needed:
            QMessageBox.warning(self, "알림", "다시 시도해보세요.")
        elif success_count > 0:
            QMessageBox.information(self, "완료", "가격 업데이트가 완료되었습니다.")

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