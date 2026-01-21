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

# WinError 6 핸들 오류 무시 패치
def suppress_del_error(self):
    try:
        self.quit()
    except Exception:
        pass

# 라이브러리의 종료 함수를 강제로 덮어씌움
uc.Chrome.__del__ = suppress_del_error

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

    def update_store_order(self, ordered_store_names):
        """스토어 순서를 DB에 업데이트 (pinned_at 시간을 조작하여 순서 제어)"""
        conn = self.get_connection()
        try:
            cursor = conn.cursor()
            base_time = datetime.now().timestamp()
            count = len(ordered_store_names)

            # 리스트의 앞쪽에 있는 스토어일수록 더 최신 시간(미래 시간)을 부여하여
            # ORDER BY DESC 조회 시 먼저 나오게 함
            for i, store_name in enumerate(ordered_store_names):
                # 순서가 앞일수록 시간을 더해서 저장
                new_time = datetime.fromtimestamp(base_time + (count - i)).strftime('%Y-%m-%d %H:%M:%S')
                
                cursor.execute('''
                    UPDATE search_presets 
                    SET pinned_at = ? 
                    WHERE store_name = ?
                ''', (new_time, store_name))
            
            conn.commit()
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
            
    def delete_search_presets_by_store(self, store_name):
        """특정 스토어명의 모든 프리셋 삭제 (탭 삭제용)"""
        conn = self.get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute('DELETE FROM search_presets WHERE store_name=?', (store_name,))
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
        """탭 순서를 유지하며 스토어 목록 반환"""
        conn = self.get_connection()
        cursor = conn.cursor()
        # pinned_at(최신순)을 기준으로 그룹화하여 정렬
        cursor.execute('''
            SELECT store_name 
            FROM search_presets 
            GROUP BY store_name 
            ORDER BY MAX(pinned_at) DESC
        ''')
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
        # 디버깅을 위해 headless를 False(화면 보임)로 강제 설정하는 것을 추천합니다.
        # 화면이 보여야 어디서 멈추는지 알 수 있습니다.
        self.headless = False  # <-- 수정 권장 (기존: headless)
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
                # 윈도우 크기를 최대로 설정 (반응형 사이트 요소 숨김 방지)
                options.add_argument("--window-size=1920,1080") 
                self.driver = uc.Chrome(options=options)
                print("✅ undetected_chromedriver(Chrome) 실행 성공")
                return
            except Exception as e:
                print(f"⚠️ UC 크롬 실행 실패, 표준 크롬으로 전환: {e}")

            # [2순위] 표준 크롬 시도
            try:
                chrome_options = webdriver.ChromeOptions()
                if self.headless:
                    chrome_options.add_argument('--headless')
                chrome_options.add_argument("--window-size=1920,1080")
                # 봇 탐지 방지 헤더 추가
                chrome_options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
                
                service = ChromeService(ChromeDriverManager().install())
                self.driver = webdriver.Chrome(service=service, options=chrome_options)
                print("✅ 표준 Chrome 실행 성공")
                return
            except Exception as e:
                print(f"⚠️ 크롬 실행 불가, 엣지(Edge)로 전환: {e}")

            # [3순위] 엣지 시도
            try:
                edge_options = webdriver.EdgeOptions()
                if self.headless:
                    edge_options.add_argument('--headless')
                edge_options.add_argument("--window-size=1920,1080")
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
            
            # [중요] 브라우저가 요소를 찾을 때까지 충분히 기다림 (최대 15초)
            from selenium.webdriver.support.ui import WebDriverWait
            from selenium.webdriver.support import expected_conditions as EC
            from selenium.webdriver.common.by import By
            
            wait = WebDriverWait(self.driver, wait_time)
            
            # 1. 요소가 존재할 때까지 대기
            # presence_of_element_located: 화면에 안 보여도 코드에 있으면 찾음
            # visibility_of_element_located: 화면에 실제로 보여야 찾음 (더 정확함)
            try:
                elem = wait.until(EC.visibility_of_element_located((By.CSS_SELECTOR, selector)))
            except:
                # visibility로 못 찾으면 presence로 재시도 (숨겨진 요소일 경우)
                elem = wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, selector)))

            # 2. 텍스트 가져오기 (innerText가 안 되면 textContent 시도)
            raw_text = elem.text.strip()
            if not raw_text:
                raw_text = elem.get_attribute('textContent').strip()
            
            print(f"🔍 추출된 텍스트: '{raw_text}'") # 디버깅용 출력

            # 3. 숫자만 추출
            digits = ''.join(filter(str.isdigit, raw_text))
            
            if digits:
                return (True, int(digits), None)
            else:
                return (False, None, f"숫자를 찾을 수 없음 (추출텍스트: {raw_text})")
                
        except Exception as e:
            return (False, None, f"크롤링 오류: {str(e)}")

    def close(self):
        """안전 종료"""
        if self.driver:
            try:
                self.driver.quit()
            except Exception:
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

class BookmarkSimpleDialog(QDialog):
    """분류 선택 없이 이름과 URL만 입력하는 간편 다이얼로그"""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("즐겨찾기 추가")
        self.setFixedSize(300, 150)
        layout = QFormLayout(self)
        
        self.name = QLineEdit()
        self.url = QLineEdit()
        self.url.setPlaceholderText("https://...")
        
        layout.addRow("사이트명:", self.name)
        layout.addRow("URL:", self.url)
        
        btns = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        btns.accepted.connect(self.validate)
        btns.rejected.connect(self.reject)
        layout.addRow(btns)

    def validate(self):
        if not self.name.text() or not self.url.text():
            QMessageBox.warning(self, "입력 오류", "사이트명과 URL을 모두 입력해주세요.")
            return
        self.accept()

    def get_data(self):
        return self.name.text(), self.url.text()

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
    """탭 순서(스토어 순서) 편집 다이얼로그"""
    def __init__(self, db, parent=None):
        super().__init__(parent)
        self.db = db
        self.setWindowTitle("스토어 탭 순서 변경")
        self.setMinimumSize(300, 400)
        layout = QVBoxLayout(self)
        
        layout.addWidget(QLabel("드래그하여 스토어(탭) 순서를 변경하세요."))
        
        self.list_widget = QListWidget()
        self.list_widget.setDragDropMode(QListWidget.DragDropMode.InternalMove)
        
        # [변경] 스토어 목록만 로드
        self.load_stores()
        
        layout.addWidget(self.list_widget)
        
        btns = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)
        layout.addWidget(btns)

    def load_stores(self):
        """중복 없이 스토어 이름만 가져와서 리스트에 표시"""
        stores = self.db.get_unique_preset_stores()
        for store_name in stores:
            # 스토어 이름만 표시
            item = QListWidgetItem(store_name)
            self.list_widget.addItem(item)

    def get_ordered_data(self):
        """재정렬된 스토어 이름 리스트 반환"""
        store_names = []
        for i in range(self.list_widget.count()):
            store_names.append(self.list_widget.item(i).text())
        return store_names


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
        QShortcut(QKeySequence("F9"), self).activated.connect(self.restore_database)

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
        db_name = self.db.db_name # 기본값 market_research_v3.db 
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
                self.load_initial_data() # UI 새로고침
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

    def get_current_path_info(self):
        """현재 선택된 아이템을 기준으로 경로(대/중/소) 분석"""
        item = self.bm_tree.currentItem()
        l, m, s = "기본", "", ""
        
        if not item:
            return l, m, s, 0 # 레벨 0 (루트)

        data = item.data(0, Qt.ItemDataRole.UserRole)
        
        # 1. 파일(즐겨찾기)을 선택한 경우 -> 부모 폴더에 추가
        if data and len(data) == 2: 
            parent = item.parent()
            if parent:
                # 부모의 데이터를 기반으로 재귀적 확인 대신, 트리 구조 역추적
                path = []
                curr = parent
                while curr:
                    path.insert(0, curr.text(0))
                    curr = curr.parent()
                l = path[0] if len(path) > 0 else "기본"
                m = path[1] if len(path) > 1 else ""
                s = path[2] if len(path) > 2 else ""
            return l, m, s, len(path) if parent else 0

        # 2. 폴더를 선택한 경우
        if data and data[0] == "FOLDER":
            level_type = data[1]
            if level_type == "LARGE":
                l = data[2]
                return l, "", "", 1
            elif level_type == "MEDIUM":
                l, m = data[2], data[3]
                return l, m, "", 2
            elif level_type == "SMALL":
                l, m, s = data[2], data[3], data[4]
                return l, m, s, 3
        
        # 예외: 그냥 텍스트로 된 폴더를 잡았을 때 (기존 데이터 호환)
        path = []
        curr = item
        while curr:
            path.insert(0, curr.text(0))
            curr = curr.parent()
        
        l = path[0] if len(path) > 0 else "기본"
        m = path[1] if len(path) > 1 else ""
        s = path[2] if len(path) > 2 else ""
        return l, m, s, len(path)

    def create_folder_action(self):
        """폴더 생성: 선택된 폴더 하위에 새 폴더 생성"""
        from PyQt6.QtWidgets import QInputDialog
        l, m, s, level = self.get_current_path_info()
        
        if level >= 3:
            QMessageBox.warning(self, "알림", "더 이상 하위 폴더를 생성할 수 없습니다. (최대 3단계)")
            return

        text, ok = QInputDialog.getText(self, "폴더 생성", "새 폴더 이름을 입력하세요:")
        if ok and text.strip():
            new_folder_name = text.strip()
            
            # 레벨에 따라 대/중/소 위치 결정
            new_l, new_m, new_s = l, m, s
            
            if level == 0: # 루트에서 생성 -> 대분류
                new_l = new_folder_name
                new_m, new_s = "", ""
            elif level == 1: # 대분류 선택 중 -> 중분류 생성
                new_m = new_folder_name
            elif level == 2: # 중분류 선택 중 -> 소분류 생성
                new_s = new_folder_name
            
            # 폴더 생성을 위해 이름/URL이 빈 더미 데이터를 추가
            self.db.add_bookmark({
                'category_large': new_l,
                'category_medium': new_m,
                'category_small': new_s,
                'site_name': '',  # 빈 값 = 폴더 인식
                'url': ''
            })
            self.refresh_bookmarks()

    def add_bookmark_simple_action(self):
        """추가 버튼: 현재 선택된 폴더 위치에 즉시 추가"""
        l, m, s, level = self.get_current_path_info()
        
        # 간편 다이얼로그 실행
        d = BookmarkSimpleDialog(self)
        if d.exec() == QDialog.DialogCode.Accepted:
            name, url = d.get_data()
            
            # DB 저장
            self.db.add_bookmark({
                'category_large': l,
                'category_medium': m,
                'category_small': s,
                'site_name': name,
                'url': url
            })
            self.refresh_bookmarks()

    def setup_ad_section(self, parent_layout):
        """하단 광고 영역 및 버튼 섹션 (광고 최적화 버전)"""
        ad_h_layout = QHBoxLayout()
        ad_h_layout.setContentsMargins(5, 5, 5, 5)
        ad_h_layout.setSpacing(10)

        # [1] 도움말 & 후원 버튼 영역 (좌측)
        self.btn_help = QPushButton("도움말 &\n버그신고")
        self.btn_help.setFixedWidth(120)
        # 높이를 광고 영역(110px)에 맞춰서 조금 늘림
        self.btn_help.setFixedHeight(110)
        self.btn_help.setStyleSheet("""
            QPushButton { background-color: #f8fafc; border: 1px solid #cbd5e1; border-radius: 8px; font-weight: bold; color: #475569; }
            QPushButton:hover { background-color: #f1f5f9; }
        """)
        self.btn_help.clicked.connect(lambda: webbrowser.open("https://rebil85.tistory.com/103#google_vignette")) 
        ad_h_layout.addWidget(self.btn_help)

        self.btn_donate = QPushButton("☕\n후원하기")
        self.btn_donate.setFixedWidth(80)
        self.btn_donate.setFixedHeight(110)
        self.btn_donate.setStyleSheet("""
            QPushButton { background-color: #fff7ed; border: 1px solid #fdba74; border-radius: 8px; font-weight: bold; color: #c2410c; }
            QPushButton:hover { background-color: #ffedd5; }
        """)
        self.btn_donate.clicked.connect(self.show_donation_dialog)
        ad_h_layout.addWidget(self.btn_donate)

        # [2] 웹뷰 광고 (중앙)
        # 애드센스 728x90 사이즈가 잘 보이도록 높이를 110px로 설정
        self.ad_view = QWebEngineView()
        self.ad_view.setFixedHeight(110) # 90px 광고가 들어가기에 충분한 높이
        self.ad_view.setFixedWidth(750)  # 728px 광고가 들어가기에 충분한 너비 (선택사항) 
        self.ad_view.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        
        # [중요] 광고가 게시된 실제 티스토리 페이지 URL 입력
        self.ad_view.setUrl(QUrl("https://rebil85.tistory.com/pages/AD-Page"))
        
        self.ad_view.setStyleSheet("border-radius: 8px; border: 1px solid #e2e8f0;")
        ad_h_layout.addWidget(self.ad_view)

        # [3] DB 관리 및 새로고침 버튼 영역 (우측)
        self.btn_main_refresh = QPushButton("🔄\n새로고침")
        self.btn_main_refresh.setFixedWidth(80)
        self.btn_main_refresh.setFixedHeight(105) # 레이아웃 균형 맞춤
        self.btn_main_refresh.setStyleSheet("""
            QPushButton { background-color: #f0f9ff; border: 1px solid #7dd3fc; border-radius: 8px; font-weight: bold; color: #0369a1; }
            QPushButton:hover { background-color: #e0f2fe; }
        """)
        self.btn_main_refresh.clicked.connect(self.load_initial_data) 
        ad_h_layout.addWidget(self.btn_main_refresh)

        # DB 백업/복구 세로 배치 레이아웃
        db_v_layout = QVBoxLayout()
        self.btn_main_backup = QPushButton("💾 DB 백업 (F8)")
        self.btn_main_backup.setFixedWidth(130)
        self.btn_main_backup.setFixedHeight(50)
        self.btn_main_backup.setStyleSheet("""
            QPushButton { background-color: white; border: 1px solid #cbd5e1; border-radius: 8px; font-weight: bold; color: #475569; }
            QPushButton:hover { background-color: #f1f5f9; }
        """)
        self.btn_main_backup.clicked.connect(self.backup_database)

        self.btn_main_restore = QPushButton("📂 DB 복구 (F9)")
        self.btn_main_restore.setFixedWidth(130)
        self.btn_main_restore.setFixedHeight(50)
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
        """홈 탭 UI - 수동입력 버튼 추가 및 불필요한 이벤트 제거 버전"""
        layout = QHBoxLayout(self.home_tab)
        splitter = QSplitter(Qt.Orientation.Horizontal)
        
        outline_style = """
            QPushButton { background-color: white;
            border: 1px solid #cbd5e1; border-radius: 4px; padding: 6px 12px; color: #475569;
            }
            QPushButton:hover { background-color: #f8fafc; border-color: #94a3b8;
            }
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
        self.p_list.itemDoubleClicked.connect(self.on_product_double_clicked)
        self.p_list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.p_list.customContextMenuRequested.connect(self.show_product_context_menu)
        v1.addWidget(self.p_list); splitter.addWidget(area1)
        
        # [2] 중앙: 히스토리
        area2 = QWidget(); v2 = QVBoxLayout(area2)
        h2 = QHBoxLayout(); h2.addWidget(QLabel("🕒 히스토리")); h2.addStretch()
        
        # 버튼들 배치 (초기화 - 엑셀 - 수동입력 - 크롤링 순서)
        btn_clear_hist = QPushButton("🗑️ 초기화"); btn_clear_hist.setStyleSheet(outline_style + "QPushButton { color: #ef4444; }")
        btn_clear_hist.clicked.connect(self.clear_current_history); h2.addWidget(btn_clear_hist)
        
        btn_excel = QPushButton("📊 엑셀"); btn_excel.setStyleSheet(outline_style); h2.addWidget(btn_excel)
        
        # [신규 추가] 수동입력 버튼
        self.btn_manual_input = QPushButton("✍️ 수동입력")
        self.btn_manual_input.setStyleSheet(outline_style + "QPushButton { color: #0ea5e9; font-weight: bold; }")
        self.btn_manual_input.clicked.connect(self.manual_input_action)
        h2.addWidget(self.btn_manual_input)
        
        btn_crawl = QPushButton("🔄 크롤링"); btn_crawl.setStyleSheet(outline_style); btn_crawl.clicked.connect(self.crawl_all_products); h2.addWidget(btn_crawl)
        
        v2.addLayout(h2)
        self.h_table = QTableWidget(0, 6)
        self.h_table.setHorizontalHeaderLabels(["날짜", "시간", "매입처", "가격", "택배비", "변동폭"])
        self.h_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        v2.addWidget(self.h_table); splitter.addWidget(area2)
        
        # [3] 우측: 가격 추이 및 즐겨찾기
        area3 = QWidget(); v3 = QVBoxLayout(area3)
        self.figure = plt.Figure(figsize=(5, 4), dpi=100); self.canvas = FigureCanvas(self.figure)
        self.ax = self.figure.add_subplot(111)
        v3.addWidget(QLabel("📈 가격 추이")); v3.addWidget(self.canvas)
        
        h_bm = QHBoxLayout(); h_bm.addWidget(QLabel("🔖 즐겨찾기")); h_bm.addStretch()
        
        # [변경] 1. 기존 '폴더추가' -> '가져오기'로 변경
        self.btn_import_bm = QPushButton("📁 가져오기")
        self.btn_import_bm.setStyleSheet(outline_style)
        self.btn_import_bm.clicked.connect(self.import_bookmarks_from_browser)
        h_bm.addWidget(self.btn_import_bm)

        # [신규] 2. '폴더생성' 버튼 추가
        self.btn_new_folder = QPushButton("📂 폴더생성")
        self.btn_new_folder.setStyleSheet(outline_style)
        self.btn_new_folder.clicked.connect(self.create_folder_action)
        h_bm.addWidget(self.btn_new_folder)
        
        # [변경] 3. '추가' 버튼 연결 함수 변경 (add_bookmark_simple_action)
        btn_add_bm = QPushButton("➕ 추가")
        btn_add_bm.setStyleSheet(outline_style)
        btn_add_bm.clicked.connect(self.add_bookmark_simple_action)
        h_bm.addWidget(btn_add_bm)
        
        v3.addLayout(h_bm)
        
        self.bm_tree = QTreeWidget(); self.bm_tree.setHeaderHidden(True)
        self.bm_tree.setDragEnabled(True); self.bm_tree.setAcceptDrops(True); self.bm_tree.setDragDropMode(QTreeWidget.DragDropMode.InternalMove)
        self.bm_tree.itemDoubleClicked.connect(self.on_bookmark_double_clicked)
        self.bm_tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu); self.bm_tree.customContextMenuRequested.connect(self.show_bookmark_context_menu)
        self.bm_tree.model().rowsMoved.connect(self.on_bookmark_dropped)
        v3.addWidget(self.bm_tree); splitter.addWidget(area3)
        
        splitter.setSizes([300, 600, 400]); layout.addWidget(splitter)

    def manual_input_action(self):
        """[✍️ 수동입력] 버튼 클릭 시 현재 선택된 상품의 수정 창을 엽니다."""
        if not self.current_product_id:
            QMessageBox.warning(self, "알림", "수동으로 입력할 상품을 먼저 리스트에서 선택해주세요.")
            return
        
        # 기존에 만들어둔 강화된 수정 다이얼로그 메서드 호출
        self.edit_product_dialog(self.current_product_id)

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
        """탭 바 우클릭 메뉴 구현 (검색어 추가 기능 포함)"""
        tab_index = self.s_preset_tabs.tabBar().tabAt(pos)
        
        # 탭 위가 아니라 빈 공간을 클릭했다면 전체 편집 메뉴만 보여줌
        if tab_index == -1:
            menu = QMenu(self)
            act_edit_all = menu.addAction("📑 스토어 순서 변경")
            if menu.exec(self.s_preset_tabs.tabBar().mapToGlobal(pos)) == act_edit_all:
                self.edit_all_presets_dialog()
            return

        menu = QMenu(self)
        menu.setStyleSheet("""
            QMenu { background-color: white; border: 1px solid #cbd5e1; }
            QMenu::item { padding: 8px 25px; }
            QMenu::item:selected { background-color: #fde047; color: #1e293b; font-weight: bold; }
        """)
        
        # ▼▼▼ [추가된 부분] 검색어 추가 메뉴 ▼▼▼
        act_add_kw = menu.addAction("➕ 이 스토어에 검색어 추가")
        menu.addSeparator() # 구분선
        # ▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲
        
        act_edit_all = menu.addAction("📑 스토어 순서 변경")
        act_modify = menu.addAction("✏️ 스토어명 수정")
        act_delete = menu.addAction("🗑️ 스토어 삭제")
        
        action = menu.exec(self.s_preset_tabs.tabBar().mapToGlobal(pos))
        
        # ▼▼▼ [추가된 부분] 클릭 시 동작 연결 ▼▼▼
        if action == act_add_kw:
            self.add_keyword_to_current_tab(tab_index)
        # ▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲
        elif action == act_edit_all:
            self.edit_all_presets_dialog()
        elif action == act_modify:
            self.modify_current_tab_dialog(tab_index)
        elif action == act_delete:
            self.delete_current_tab(tab_index)
            
    def add_keyword_to_current_tab(self, index):
        """우클릭한 스토어 탭에 새로운 검색어 추가"""
        from PyQt6.QtWidgets import QInputDialog # 입력 다이얼로그 사용을 위해 필요
        
        # 1. 현재 탭의 스토어 이름 가져오기
        store_name = self.s_preset_tabs.tabText(index)
        
        # 2. 입력창 띄우기
        text, ok = QInputDialog.getText(self, "검색어 추가", 
                                      f"[{store_name}] 스토어에 추가할 키워드를 입력하세요:")
        
        if ok and text.strip():
            # 3. DB에 저장 (기존 메서드 재사용)
            self.db.add_search_preset(store_name, text.strip())
            
            # 4. 화면 갱신
            self.refresh_search_presets()
            
            # 5. 편의를 위해 방금 추가한 탭으로 이동
            for i in range(self.s_preset_tabs.count()):
                if self.s_preset_tabs.tabText(i) == store_name:
                    self.s_preset_tabs.setCurrentIndex(i)
                    break
                    
            self.statusBar().showMessage(f"✅ '{store_name}'에 검색어가 추가되었습니다.", 3000)

    def edit_all_presets_dialog(self):
        """스토어 탭 순서 변경 다이얼로그 실행"""
        d = PresetReorderDialog(self.db, self)
        if d.exec() == QDialog.DialogCode.Accepted:
            # 1. 변경된 스토어 순서 리스트 가져오기 (예: ['스토어B', '스토어A'])
            new_order_list = d.get_ordered_data()
            
            # 2. DB에 순서 업데이트 (스토어 단위)
            self.db.update_store_order(new_order_list)
            
            # 3. UI 탭 새로고침
            self.refresh_search_presets()
            
            QMessageBox.information(self, "완료", "탭 순서가 변경되었습니다.")

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
        # 1. 현재 선택된 탭의 이름(스토어명)을 가져옵니다.
        store_name = self.s_preset_tabs.tabText(index)
        
        # 2. 삭제 확인 메시지
        if QMessageBox.question(self, "탭 삭제", 
                              f"[{store_name}] 탭과 포함된 모든 검색어를 정말 삭제하시겠습니까?\n(복구할 수 없습니다)",
                              QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No) == QMessageBox.StandardButton.Yes:
            
            # 3. DB에서 해당 스토어명 데이터 전체 삭제
            self.db.delete_search_presets_by_store(store_name)
            
            # 4. 화면 갱신
            self.refresh_search_presets()
            QMessageBox.information(self, "완료", "탭이 삭제되었습니다.")
        
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
        self.manage_table.setSortingEnabled(True) 
        
        # ▼▼▼ [수정된 부분] 수정 방지 및 더블클릭 연결 ▼▼▼
        from PyQt6.QtWidgets import QAbstractItemView
        # 1. 테이블 수정 불가(읽기 전용) 설정
        self.manage_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        # 2. 더블클릭 시 URL 열기 기능 연결
        self.manage_table.itemDoubleClicked.connect(self.on_manage_table_double_clicked)
        # ▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲
        
        # 헤더 사이즈 정책 (이전 요청사항 유지)
        header = self.manage_table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents) # ID
        header.setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents) # 현재가
        header.setSectionResizeMode(5, QHeaderView.ResizeMode.ResizeToContents) # 택배비
        
        layout.addWidget(self.manage_table)
        
        btn_group = QHBoxLayout()
        self.btn_m_edit = QPushButton("✏️ 선택 수정"); self.btn_m_edit.clicked.connect(self.edit_selected_product); btn_group.addWidget(self.btn_m_edit)
        self.btn_m_del = QPushButton("🗑️ 선택 삭제"); self.btn_m_del.setStyleSheet("background:#fee2e2; color:#b91c1c;"); self.btn_m_del.clicked.connect(self.delete_selected_product); btn_group.addWidget(self.btn_m_del)
        
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
        
    def on_manage_table_double_clicked(self, item):
        """관리 탭 테이블 더블클릭 시 URL 열기"""
        row = item.row()
        # 컬럼 인덱스 6번이 URL입니다. (ID=0, 카테고리=1, ... URL=6)
        url_item = self.manage_table.item(row, 6)
        
        if url_item:
            url = url_item.text().strip()
            if url.startswith('http'):
                webbrowser.open(url)
            else:
                QMessageBox.warning(self, "알림", "유효한 URL 정보가 없습니다.")
    
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
        
    def on_product_double_clicked(self, item):
        """상품 리스트 아이템 더블 클릭 시 등록된 URL 열기"""
        p_id = item.data(Qt.ItemDataRole.UserRole)
        p = self.db.get_product_by_id(p_id)
        if p and p[7]: # p[7]은 DB의 url 컬럼입니다.
            webbrowser.open(p[7])

    def update_history_and_graph(self):
        """히스토리 표 갱신 및 변동폭 색상 적용"""
        if not self.current_product_id: return
        hist = self.db.get_price_history(self.current_product_id)
        
        self.h_table.setRowCount(len(hist))
        for i, h in enumerate(hist):
            # h[2]:날짜, h[3]:시간, h[6]:매입처, h[4]:가격, h[5]:택배비
            self.h_table.setItem(i, 0, QTableWidgetItem(h[2]))
            self.h_table.setItem(i, 1, QTableWidgetItem(h[3]))
            self.h_table.setItem(i, 2, QTableWidgetItem(h[6] or "-"))
            self.h_table.setItem(i, 3, QTableWidgetItem(f"{h[4]:,}원"))
            self.h_table.setItem(i, 4, QTableWidgetItem(f"{h[5]:,}원"))
            
            # 변동폭 계산 및 색상 적용
            diff_item = QTableWidgetItem("-")
            if i < len(hist) - 1:
                # 현재 가격 - 이전 기록 가격
                d = h[4] - hist[i+1][4]
                if d > 0:
                    diff_item.setText(f"▲{d:,}")
                    diff_item.setForeground(QColor("#ef4444")) # 빨간색 (상승)
                elif d < 0:
                    diff_item.setText(f"▼{abs(d):,}")
                    diff_item.setForeground(QColor("#3b82f6")) # 파란색 (하락)
            
            diff_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.h_table.setItem(i, 5, diff_item)
    
        # 그래프 갱신 로직 (기존 유지)
        sorted_h = sorted(hist, key=lambda x: (x[2], x[3]))
        if sorted_h:
            dates = [h[2] for h in sorted_h]
            prices = [h[4] for h in sorted_h]
            self.ax.clear()
            self.ax.plot(dates, prices, marker='o', color='#4f46e5')
            self.ax.tick_params(axis='x', rotation=45, labelsize=8)
            self.figure.tight_layout()
            self.canvas.draw()

    # ========== 즐겨찾기 로직 (개선) ==========
    def add_bookmark_dialog(self):
        d = BookmarkDialog(self.db, self)
        if d.exec() == QDialog.DialogCode.Accepted:
            self.db.add_bookmark(d.get_data())
            self.refresh_bookmarks()

    def refresh_bookmarks(self):
        """즐겨찾기 목록 갱신 (기본 닫힘 상태)"""
        self.bm_tree.clear()
        from PyQt6.QtWidgets import QStyle
        folder_icon = self.style().standardIcon(QStyle.StandardPixmap.SP_DirIcon)
        file_icon = self.style().standardIcon(QStyle.StandardPixmap.SP_FileIcon)
        
        tree_data = self.db.get_all_bookmarks()
        
        for l, mediums in tree_data.items():
            l_item = QTreeWidgetItem(self.bm_tree, [l])
            l_item.setIcon(0, folder_icon)
            l_item.setData(0, Qt.ItemDataRole.UserRole, ("FOLDER", "LARGE", l))

            for m, smalls in mediums.items():
                if not m: pass 
                
                m_node = QTreeWidgetItem(l_item, [m]) if m else l_item
                if m: 
                    m_node.setIcon(0, folder_icon)
                    m_node.setData(0, Qt.ItemDataRole.UserRole, ("FOLDER", "MEDIUM", l, m))

                for s, sites in smalls.items():
                    s_node = QTreeWidgetItem(m_node, [s]) if s else m_node
                    if s: 
                        s_node.setIcon(0, folder_icon)
                        s_node.setData(0, Qt.ItemDataRole.UserRole, ("FOLDER", "SMALL", l, m, s))
                    
                    for name, url, b_id in sites:
                        if not name or not url: continue
                            
                        site_item = QTreeWidgetItem(s_node, [name])
                        site_item.setIcon(0, file_icon)
                        site_item.setData(0, Qt.ItemDataRole.UserRole, (url, b_id))
        
        # [수정됨] 기본적으로 모두 닫힌 상태로 시작
        self.bm_tree.collapseAll()

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
            
            # ▼▼▼ [추가해야 할 부분] 우클릭 메뉴 활성화 코드 ▼▼▼
            lw.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
            lw.customContextMenuRequested.connect(self.show_preset_list_context_menu)
            # ▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲
            
            self.s_preset_tabs.addTab(lw, s)

    # 기존 코드 아래에 이 함수들을 새로 추가해주세요.

    def show_preset_list_context_menu(self, pos):
        """검색어 리스트 아이템 우클릭 메뉴"""
        # 신호를 보낸 리스트 위젯을 찾습니다 (sender 사용)
        lw = self.sender()
        item = lw.itemAt(pos)
        if not item: return

        # 데이터 가져오기 (ID, Store, Keyword)
        data = item.data(Qt.ItemDataRole.UserRole)
        if not data: return

        menu = QMenu()
        # 다른 메뉴들과 동일한 디자인 적용
        menu.setStyleSheet("""
            QMenu { background-color: white; border: 1px solid #cbd5e1; }
            QMenu::item { padding: 8px 25px; }
            QMenu::item:selected { background-color: #fde047; color: #1e293b; font-weight: bold; }
        """)
        
        del_act = menu.addAction("🗑️ 검색어 삭제")
        
        # 메뉴 실행
        action = menu.exec(lw.mapToGlobal(pos))
        
        if action == del_act:
            self.delete_search_preset_item(data)

    def delete_search_preset_item(self, data):
        """실제 DB에서 검색어 삭제"""
        preset_id, store, keyword = data
        
        if QMessageBox.question(self, "삭제 확인", 
                              f"[{store}] '{keyword}'\n이 검색어를 정말 삭제하시겠습니까?") == QMessageBox.StandardButton.Yes:
            self.db.delete_search_preset(preset_id)
            self.refresh_search_presets() # 목록 새로고침
            QMessageBox.information(self, "삭제 완료", "삭제되었습니다.")
            
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
        """관리 탭의 선택 수정 버튼 로직 (히스토리 동시 반영)"""
        row = self.manage_table.currentRow()
        if row < 0: return
        # 테이블의 첫 번째 컬럼(ID)을 가져옵니다.
        p_id = int(self.manage_table.item(row, 0).text())
        # 위에서 만든 강화된 수정 메서드 호출
        self.edit_product_dialog(p_id)

    def edit_product_dialog(self, p_id):
        """상품 정보 수정 시 히스토리에 즉시 반영하여 적용 안 됨 문제 해결"""
        prods = self.db.get_all_products()
        p = next((x for x in prods if x[0] == p_id), None)
        if not p: return
        
        d = ProductDialog(self.db, p, self)
        if d.exec() == QDialog.DialogCode.Accepted:
            data = d.get_data()
            
            # 1. 상품 메인 정보 업데이트 (DB)
            self.db.update_product(p_id, data)
            
            # 2. [중요] 수정된 가격을 히스토리에 추가해야 화면에 즉시 반영됩니다.
            # 이 기록이 추가되어야 '현재가'와 '히스토리 표'가 모두 갱신됩니다.
            self.db.add_price_history(p_id, data['price'], data.get('delivery_fee', 0), data['vendor'])
            
            # UI 새로고침
            self.load_initial_data()
            if self.current_product_id == p_id:
                self.update_history_and_graph()
            
            self.statusBar().showMessage("✅ 정보가 수정되어 히스토리에 반영되었습니다.", 3000)

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
        """홈 탭 우클릭 수정 시 히스토리에도 새 가격 기록"""
        prods = self.db.get_all_products()
        p = next((x for x in prods if x[0] == p_id), None)
        d = ProductDialog(self.db, p, self)
        
        if d.exec() == QDialog.DialogCode.Accepted:
            data = d.get_data()
            # 1. 상품 정보 업데이트
            self.db.update_product(p_id, data)
            # 2. [추가] 수정된 가격을 히스토리에 즉시 반영
            self.db.add_price_history(p_id, data['price'], data.get('delivery_fee', 0), data['vendor'])
            # 3. UI 전체 갱신
            self.load_initial_data()
            if self.current_product_id == p_id:
                self.update_history_and_graph()

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
        """크롤링 완료 후 처리 (기존 택배비 유지 기능 추가)"""
        success_count = 0
        failure_occurred = False

        for p_id, price, success, info in results:
            if not success:
                # 실패 시 수동 등록 안내 및 창 띄우기
                QMessageBox.information(self, "수동 등록 안내", 
                                       f"[{info.get('vendor', '알수없음')}] 보안 문제로 자동 크롤링 실패.\n가격을 수동으로 업데이트해주세요.")
                self.edit_product_dialog(p_id)
                failure_occurred = True
            else:
                # 성공 시 DB 저장
                # [중요] 기존 상품 정보를 불러와서 택배비를 유지해야 함
                p = self.db.get_product_by_id(p_id)
                
                if p:
                    current_vendor = p[5]
                    # p[11]이 기존 저장된 택배비입니다.
                    existing_fee = p[11]
                    
                    # 크롤러가 택배비를 못 가져왔으면(info에 없으면) 기존 택배비(existing_fee) 사용
                    final_fee = info.get('delivery_fee', existing_fee)
                    
                    self.db.add_price_history(p_id, price, final_fee, current_vendor)
                    success_count += 1

        # UI 및 테이블 새로고침
        self.load_initial_data()
        if self.current_product_id:
            self.update_history_and_graph()

        if success_count > 0:
            self.statusBar().showMessage(f"✅ {success_count}건의 가격 업데이트가 완료되었습니다.", 3000)

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