import sys
import sqlite3
import requests
from datetime import datetime
from bs4 import BeautifulSoup

from selenium import webdriver
from selenium.webdriver.edge.service import Service
from selenium.webdriver.edge.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.microsoft import EdgeChromiumDriverManager

# PyQt6 라이브러리 임포트
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QSplitter, QListWidget, QListWidgetItem, QLabel, QLineEdit,
    QPushButton, QTableWidget, QTableWidgetItem, QHeaderView,
    QTreeWidget, QTreeWidgetItem, QMessageBox, QFrame, QTabWidget,
    QDialog, QComboBox, QTextEdit, QFormLayout, QDialogButtonBox,
    QProgressDialog, QSpinBox, QMenu
)

from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtGui import QFont, QColor

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
    """SQLite 데이터베이스 관리"""
    
    def __init__(self, db_name="market_research.db"):
        self.db_name = db_name
        self.init_database()
    
    def get_connection(self):
        """DB 연결 반환"""
        return sqlite3.connect(self.db_name)
    
    def init_database(self):
        """데이터베이스 초기화 (테이블 생성)"""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        # 상품 테이블
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
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        # 가격 히스토리 테이블
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

        # 기존 DB에 delivery_fee 컬럼 추가
        try:
            cursor.execute("ALTER TABLE price_history ADD COLUMN delivery_fee INTEGER DEFAULT 0")
        except sqlite3.OperationalError:
            pass  # 이미 컬럼이 있으면 패스
        
        # 즐겨찾기 테이블
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS bookmarks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                category_large TEXT NOT NULL,
                category_medium TEXT,
                category_small TEXT,
                site_name TEXT NOT NULL,
                url TEXT NOT NULL
            )
        ''')
        
        conn.commit()
        conn.close()
    
    # ========== 상품 관련 메서드 ==========
    def add_product(self, data):
        """상품 추가"""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute('''
            INSERT INTO products 
            (category_large, category_medium, category_small, product_name, 
             vendor, price, url, css_selector, memo)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            data['category_large'], data['category_medium'], data['category_small'],
            data['product_name'], data['vendor'], data['price'],
            data['url'], data['css_selector'], data['memo']
        ))
        product_id = cursor.lastrowid
        
        # 첫 히스토리 자동 생성
        cursor.execute('''
            INSERT INTO price_history (product_id, crawled_date, crawled_time, price, delivery_fee, vendor)
            VALUES (?, ?, ?, ?, ?, ?)
        ''', (
            product_id,
            now.strftime('%Y-%m-%d'),
            now.strftime('%H:%M:%S'),
            data['price'],
            data.get('delivery_fee', 0),
            data['vendor']
        ))
        
        conn.commit()
        conn.close()
        return product_id
    
    def get_all_products(self, search_term=""):
        """모든 상품 조회 (검색어 필터링)"""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        if search_term:
            cursor.execute('''
                SELECT * FROM products 
                WHERE product_name LIKE ? OR vendor LIKE ?
                ORDER BY created_at DESC
            ''', (f'%{search_term}%', f'%{search_term}%'))
        else:
            cursor.execute('SELECT * FROM products ORDER BY created_at DESC')
        
        products = cursor.fetchall()
        conn.close()
        return products
    
    def update_product(self, product_id, data):
        """상품 정보 수정"""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute('''
            UPDATE products SET
                category_large=?, category_medium=?, category_small=?,
                product_name=?, vendor=?, price=?, url=?, css_selector=?, memo=?
            WHERE id=?
        ''', (
            data['category_large'], data['category_medium'], data['category_small'],
            data['product_name'], data['vendor'], data['price'],
            data['url'], data['css_selector'], data['memo'], product_id
        ))
        conn.commit()
        conn.close()
    
    def delete_product(self, product_id):
        """상품 삭제 (히스토리도 함께 삭제)"""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute('DELETE FROM price_history WHERE product_id=?', (product_id,))
        cursor.execute('DELETE FROM products WHERE id=?', (product_id,))
        conn.commit()
        conn.close()
    
    # ========== 히스토리 관련 메서드 ==========
    def add_price_history(self, product_id, price, delivery_fee=0, vendor=None):
        """가격 히스토리 추가 (택배비 포함)"""
        conn = self.get_connection()
        cursor = conn.cursor()
        now = datetime.now()
        
        # delivery_fee 컬럼을 포함하도록 INSERT 쿼리 수정 
        cursor.execute('''
            INSERT INTO price_history (product_id, crawled_date, crawled_time, price, delivery_fee, vendor)
            VALUES (?, ?, ?, ?, ?, ?)
        ''', (
            product_id, 
            now.strftime('%Y-%m-%d'), 
            now.strftime('%H:%M:%S'), 
            price, 
            delivery_fee, 
            vendor
        ))
        
        conn.commit()
        conn.close()
    
    def get_price_history(self, product_id):
        """상품의 가격 히스토리 조회"""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute('''
            SELECT id, product_id, crawled_date, crawled_time, price, delivery_fee, vendor
            FROM price_history
            WHERE product_id = ?
            ORDER BY crawled_date DESC, crawled_time DESC
        ''', (product_id,))
        history = cursor.fetchall()
        conn.close()
        return history
    
    def delete_price_history(self, history_id):
        """특정 히스토리 삭제"""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute('DELETE FROM price_history WHERE id=?', (history_id,))
        conn.commit()
        conn.close()

    # ========== 즐겨찾기 관련 메서드 ==========
    def add_bookmark(self, data):
        """즐겨찾기 추가"""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute('''
            INSERT INTO bookmarks (category_large, category_medium, category_small, site_name, url)
            VALUES (?, ?, ?, ?, ?)
        ''', (data['category_large'], data['category_medium'], 
              data['category_small'], data['site_name'], data['url']))
        conn.commit()
        conn.close()
    
    def get_all_bookmarks(self):
        """모든 즐겨찾기 조회 (계층 구조로 반환)"""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute('SELECT * FROM bookmarks')
        bookmarks = cursor.fetchall()
        conn.close()
        
        # 계층 구조로 변환
        tree = {}
        for bm in bookmarks:
            large = bm[1]
            medium = bm[2] or ""
            small = bm[3] or ""
            name = bm[4]
            url = bm[5]
            
            if large not in tree:
                tree[large] = {}
            if medium and medium not in tree[large]:
                tree[large][medium] = {}
            
            if small:
                if small not in tree[large][medium]:
                    tree[large][medium][small] = []
                tree[large][medium][small].append((name, url))
            elif medium:
                if 'sites' not in tree[large][medium]:
                    tree[large][medium]['sites'] = []
                tree[large][medium]['sites'].append((name, url))
            else:
                if 'sites' not in tree[large]:
                    tree[large]['sites'] = []
                tree[large]['sites'].append((name, url))
        
        return tree
    
    def delete_bookmark(self, bookmark_id):
        """즐겨찾기 삭제"""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute('DELETE FROM bookmarks WHERE id=?', (bookmark_id,))
        conn.commit()
        conn.close()
    
    def get_bookmark_by_url(self, url):
        """URL로 즐겨찾기 ID 찾기"""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute('SELECT id FROM bookmarks WHERE url=?', (url,))
        result = cursor.fetchone()
        conn.close()
        return result[0] if result else None

    # ========== 카테고리 관련 메서드 ==========
    def get_unique_categories(self, level='large'):
        """고유 카테고리 목록 반환"""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        if level == 'large':
            cursor.execute('SELECT DISTINCT category_large FROM products WHERE category_large IS NOT NULL')
        elif level == 'medium':
            cursor.execute('SELECT DISTINCT category_medium FROM products WHERE category_medium IS NOT NULL')
        else:  # small
            cursor.execute('SELECT DISTINCT category_small FROM products WHERE category_small IS NOT NULL')
        
        categories = [row[0] for row in cursor.fetchall()]
        conn.close()
        return sorted(categories)


# ============================================================
# Selenium 크롤러 클래스
# ============================================================
class SeleniumCrawler:
    """Selenium을 사용한 동적 웹페이지 크롤링"""
    
    def __init__(self, headless=True):
        self.headless = headless
        self.driver = None
    
    def init_driver(self):
        """Edge 드라이버 초기화"""
        import os
        
        edge_options = Options()
        
        if self.headless:
            edge_options.add_argument('--headless')
        
        edge_options.add_argument('--no-sandbox')
        edge_options.add_argument('--disable-dev-shm-usage')
        edge_options.add_argument('--disable-blink-features=AutomationControlled')
        edge_options.add_argument('--disable-gpu')
        edge_options.add_argument('--window-size=1920,1080')
        edge_options.add_argument('--inprivate')
        edge_options.add_argument('--log-level=3')
        edge_options.add_argument('user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36 Edg/120.0.0.0')
        edge_options.add_experimental_option("excludeSwitches", ["enable-automation"])
        edge_options.add_experimental_option('useAutomationExtension', False)
        
        try:
            # 현재 스크립트 폴더에서 msedgedriver.exe 찾기
            current_dir = os.path.dirname(os.path.abspath(__file__))
            driver_path = os.path.join(current_dir, 'msedgedriver.exe')
            
            if os.path.exists(driver_path):
                # 수동 설치된 드라이버 사용
                service = Service(driver_path)
                self.driver = webdriver.Edge(service=service, options=edge_options)
                print(f"✅ 로컬 드라이버 사용: {driver_path}")
            else:
                # 시스템 PATH에서 찾기
                self.driver = webdriver.Edge(options=edge_options)
                print("✅ 시스템 드라이버 사용")
            
            # 자동화 탐지 우회
            try:
                self.driver.execute_cdp_cmd('Page.addScriptToEvaluateOnNewDocument', {
                    'source': '''
                        Object.defineProperty(navigator, 'webdriver', {
                            get: () => undefined
                        })
                    '''
                })
            except:
                pass
                
        except Exception as e:
            raise Exception(
                f"Edge 드라이버 초기화 실패: {str(e)}\n\n"
                f"해결 방법:\n"
                f"1. msedgedriver.exe를 다운로드하세요:\n"
                f"   https://developer.microsoft.com/en-us/microsoft-edge/tools/webdriver/\n"
                f"2. 파일을 아래 폴더에 복사하세요:\n"
                f"   {current_dir}\n"
                f"3. Edge 버전과 드라이버 버전이 일치해야 합니다!"
            )
    
    def get_price(self, url, css_selector, wait_time=10):
        """
        URL에서 가격 추출
        
        Args:
            url: 크롤링할 URL
            css_selector: CSS Selector
            wait_time: 최대 대기 시간 (초)
        
        Returns:
            (success, price, error_message)
        """
        if not self.driver:
            self.init_driver()
        
        try:
            # 페이지 로드
            self.driver.get(url)
            
            # 요소가 나타날 때까지 대기
            wait = WebDriverWait(self.driver, wait_time)
            element = wait.until(
                EC.presence_of_element_located((By.CSS_SELECTOR, css_selector))
            )
            
            # 텍스트 추출
            price_text = element.text.strip()
            
            # 숫자만 추출
            digits = ''.join(filter(str.isdigit, price_text))
            
            if digits:
                return (True, int(digits), None)
            else:
                return (False, None, f"숫자 추출 실패 (텍스트: '{price_text}')")
        
        except Exception as e:
            return (False, None, str(e))
    
    def close(self):
        """드라이버 종료"""
        if self.driver:
            self.driver.quit()
            self.driver = None

# ============================================================
# 크롤링 워커 스레드
# ============================================================
class CrawlWorker(QThread):
    """백그라운드 크롤링 작업"""
    progress = pyqtSignal(int, str)  # (진행률, 메시지)
    finished = pyqtSignal(list)  # [(product_id, new_price, success), ...]
    
    def __init__(self, products_data, use_selenium=False):
        super().__init__()
        self.products_data = products_data  # [(id, url, css_selector, vendor), ...]
        self.use_selenium = use_selenium
    
    def run(self):
        results = []
        total = len(self.products_data)
        
        # Selenium 모드
        if self.use_selenium:
            selenium_crawler = SeleniumCrawler(headless=True)
            
            try:
                for i, (p_id, url, css_selector, vendor) in enumerate(self.products_data):
                    debug_info = {
                        'product_id': p_id,
                        'vendor': vendor,
                        'url': url,
                        'selector': css_selector,
                        'status': 'pending',
                        'method': 'Selenium'
                    }
                    
                    self.progress.emit(int((i / total) * 100), f"Selenium 크롤링: {vendor}")
                    
                    if not url or not css_selector:
                        debug_info['status'] = 'failed'
                        debug_info['error'] = 'URL 또는 CSS Selector가 비어있음'
                        results.append((p_id, None, False, debug_info))
                        continue
                    
                    # Selenium으로 가격 추출
                    success, price, error = selenium_crawler.get_price(url, css_selector)
                    
                    if success:
                        debug_info['status'] = 'success'
                        debug_info['extracted_price'] = price
                        debug_info['found_text'] = f"{price}원"
                        results.append((p_id, price, True, debug_info))
                    else:
                        debug_info['status'] = 'failed'
                        debug_info['error'] = f'Selenium 크롤링 실패: {error}'
                        results.append((p_id, None, False, debug_info))
                    
                    # 딜레이
                    import time
                    import random
                    time.sleep(random.uniform(1.5, 3.0))
            
            finally:
                selenium_crawler.close()
        
        # 기존 requests 모드
        else:
            session = requests.Session()
            session.headers.update({
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
                'Accept-Language': 'ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7',
                'Accept-Encoding': 'gzip, deflate, br',
                'DNT': '1',
                'Connection': 'keep-alive',
                'Upgrade-Insecure-Requests': '1'
            })
            
            for i, (p_id, url, css_selector, vendor) in enumerate(self.products_data):
                debug_info = {
                    'product_id': p_id,
                    'vendor': vendor,
                    'url': url,
                    'selector': css_selector,
                    'status': 'pending',
                    'method': 'Requests'
                }
                
                try:
                    self.progress.emit(int((i / total) * 100), f"크롤링 중: {vendor}")
                    
                    if not url or not css_selector:
                        debug_info['status'] = 'failed'
                        debug_info['error'] = 'URL 또는 CSS Selector가 비어있음'
                        results.append((p_id, None, False, debug_info))
                        continue
                    
                    # 딜레이
                    import time
                    import random
                    delay = random.uniform(2.0, 4.0)
                    self.progress.emit(int((i / total) * 100), f"대기 중... ({delay:.1f}초)")
                    time.sleep(delay)
                    
                    # Referer 헤더
                    from urllib.parse import urlparse
                    parsed_url = urlparse(url)
                    base_url = f"{parsed_url.scheme}://{parsed_url.netloc}"
                    
                    # HTTP 요청
                    debug_info['request_sent'] = True
                    response = session.get(
                        url, 
                        headers={'Referer': base_url},
                        timeout=15,
                        allow_redirects=True
                    )
                    debug_info['status_code'] = response.status_code
                    debug_info['response_size'] = len(response.content)
                    
                    if response.status_code == 429:
                        debug_info['status'] = 'failed'
                        debug_info['error'] = 'HTTP 429 - 요청 제한 초과\n💡 Selenium 모드를 사용해보세요'
                        results.append((p_id, None, False, debug_info))
                        continue
                    elif response.status_code == 403:
                        debug_info['status'] = 'failed'
                        debug_info['error'] = 'HTTP 403 - 접근 거부\n💡 Selenium 모드를 사용해보세요'
                        results.append((p_id, None, False, debug_info))
                        continue
                    
                    response.raise_for_status()
                    
                    # HTML 파싱
                    soup = BeautifulSoup(response.content, 'html.parser')
                    debug_info['html_parsed'] = True
                    
                    # CSS Selector로 요소 찾기
                    price_element = soup.select_one(css_selector)
                    
                    if price_element:
                        price_text = price_element.get_text(strip=True)
                        debug_info['found_text'] = price_text
                        
                        digits = ''.join(filter(str.isdigit, price_text))
                        
                        if digits:
                            price = int(digits)
                            debug_info['status'] = 'success'
                            debug_info['extracted_price'] = price
                            results.append((p_id, price, True, debug_info))
                        else:
                            debug_info['status'] = 'failed'
                            debug_info['error'] = f'숫자 추출 실패 (텍스트: "{price_text}")'
                            results.append((p_id, None, False, debug_info))
                    else:
                        debug_info['status'] = 'failed'
                        debug_info['error'] = 'CSS Selector로 요소를 찾지 못함\n💡 Selenium 모드를 시도해보세요'
                        
                        similar = soup.find_all(class_=True)
                        if similar:
                            classes = []
                            for elem in similar[:20]:
                                elem_classes = elem.get('class', [])
                                if elem_classes:
                                    classes.append('.'.join(elem_classes))
                            debug_info['similar_classes'] = classes
                        
                        results.append((p_id, None, False, debug_info))
                
                except requests.exceptions.Timeout:
                    debug_info['status'] = 'failed'
                    debug_info['error'] = '요청 시간 초과 (15초)'
                    results.append((p_id, None, False, debug_info))
                
                except requests.exceptions.ConnectionError:
                    debug_info['status'] = 'failed'
                    debug_info['error'] = '연결 실패'
                    results.append((p_id, None, False, debug_info))
                
                except Exception as e:
                    debug_info['status'] = 'failed'
                    debug_info['error'] = f'오류: {str(e)}'
                    results.append((p_id, None, False, debug_info))
            
            session.close()
        
        self.progress.emit(100, "완료")
        self.finished.emit(results)


# ============================================================
# 크롤링 디버그 다이얼로그
# ============================================================
class CrawlDebugDialog(QDialog):
    """크롤링 결과 상세 보기"""
    
    def __init__(self, results, parent=None):
        super().__init__(parent)
        self.results = results
        self.init_ui()
    
    def init_ui(self):
        self.setWindowTitle("크롤링 결과 상세보기")
        self.resize(900, 600)
        
        layout = QVBoxLayout(self)
        
        # 타이틀
        title = QLabel("🔍 크롤링 디버그 정보")
        title.setFont(QFont("Malgun Gothic", 14, QFont.Weight.Bold))
        layout.addWidget(title)
        
        # 탭 위젯
        tabs = QTabWidget()
        
        # 성공/실패 분류
        success_results = [r for r in self.results if r[2]]
        failed_results = [r for r in self.results if not r[2]]
        
        # 성공 탭
        success_widget = QWidget()
        success_layout = QVBoxLayout(success_widget)
        success_label = QLabel(f"✅ 성공: {len(success_results)}개")
        success_label.setStyleSheet("color: green; font-weight: bold; font-size: 12px;")
        success_layout.addWidget(success_label)
        
        success_text = QTextEdit()
        success_text.setReadOnly(True)
        for p_id, price, success, debug in success_results:
            success_text.append(f"상품 ID: {p_id}")
            success_text.append(f"판매처: {debug.get('vendor', 'N/A')}")
            success_text.append(f"추출 가격: {price:,}원")
            success_text.append(f"원본 텍스트: {debug.get('found_text', 'N/A')}")
            success_text.append("-" * 60 + "\n")
        success_layout.addWidget(success_text)
        tabs.addTab(success_widget, f"✅ 성공 ({len(success_results)})")
        
        # 실패 탭
        failed_widget = QWidget()
        failed_layout = QVBoxLayout(failed_widget)
        failed_label = QLabel(f"❌ 실패: {len(failed_results)}개")
        failed_label.setStyleSheet("color: red; font-weight: bold; font-size: 12px;")
        failed_layout.addWidget(failed_label)
        
        failed_text = QTextEdit()
        failed_text.setReadOnly(True)
        failed_text.setStyleSheet("font-family: 'Consolas', monospace;")
        
        for p_id, price, success, debug in failed_results:
            failed_text.append("=" * 70)
            failed_text.append(f"📦 상품 ID: {p_id} | 판매처: {debug.get('vendor', 'N/A')}")
            failed_text.append("=" * 70)
            failed_text.append(f"🔗 URL: {debug.get('url', 'N/A')}")
            failed_text.append(f"🎯 CSS Selector: {debug.get('selector', 'N/A')}")
            failed_text.append("")
            failed_text.append(f"❌ 오류: {debug.get('error', '알 수 없음')}")
            failed_text.append("")
            
            # 추가 정보
            if 'status_code' in debug:
                failed_text.append(f"📡 HTTP 상태 코드: {debug['status_code']}")
            if 'response_size' in debug:
                failed_text.append(f"📄 응답 크기: {debug['response_size']:,} bytes")
            if 'found_text' in debug:
                failed_text.append(f"📝 발견된 텍스트: {debug['found_text']}")
            if 'similar_classes' in debug:
                failed_text.append(f"💡 유사 클래스: {debug['similar_classes'][:5]}")
            
            failed_text.append("\n")
        
        failed_layout.addWidget(failed_text)
        tabs.addTab(failed_widget, f"❌ 실패 ({len(failed_results)})")
        
        layout.addWidget(tabs)
        
        # 닫기 버튼
        close_btn = QPushButton("닫기")
        close_btn.clicked.connect(self.close)
        layout.addWidget(close_btn)

# ============================================================
# 즐겨찾기 추가 다이얼로그
# ============================================================
class BookmarkDialog(QDialog):
    """즐겨찾기 추가 다이얼로그"""
    
    def __init__(self, db_manager, parent=None):
        super().__init__(parent)
        self.db = db_manager
        self.init_ui()
    
    def init_ui(self):
        self.setWindowTitle("즐겨찾기 추가")
        self.setMinimumWidth(450)
        
        layout = QVBoxLayout(self)
        form_layout = QFormLayout()
        
        # 카테고리 대분류
        self.combo_large = QComboBox()
        self.combo_large.setEditable(True)
        self.combo_large.addItems(self.db.get_unique_categories('large'))
        form_layout.addRow("대분류*:", self.combo_large)
        
        # 카테고리 중분류
        self.combo_medium = QComboBox()
        self.combo_medium.setEditable(True)
        self.combo_medium.addItems(self.db.get_unique_categories('medium'))
        form_layout.addRow("중분류:", self.combo_medium)
        
        # 카테고리 소분류
        self.combo_small = QComboBox()
        self.combo_small.setEditable(True)
        self.combo_small.addItems(self.db.get_unique_categories('small'))
        form_layout.addRow("소분류:", self.combo_small)
        
        # 사이트명
        self.input_site_name = QLineEdit()
        self.input_site_name.setPlaceholderText("예: 쿠팡 남성복 카테고리")
        form_layout.addRow("사이트명*:", self.input_site_name)
        
        # URL
        self.input_url = QLineEdit()
        self.input_url.setPlaceholderText("https://...")
        form_layout.addRow("URL*:", self.input_url)
        
        layout.addLayout(form_layout)
        
        # 안내 문구
        info_label = QLabel("💡 즐겨찾기를 더블클릭하면 브라우저로 열립니다.")
        info_label.setStyleSheet("color: #6b7280; font-size: 11px; margin-top: 8px;")
        layout.addWidget(info_label)
        
        # 버튼
        button_box = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        button_box.accepted.connect(self.accept)
        button_box.rejected.connect(self.reject)
        layout.addWidget(button_box)
    
    def get_data(self):
        """입력된 데이터 반환"""
        return {
            'category_large': self.combo_large.currentText(),
            'category_medium': self.combo_medium.currentText(),
            'category_small': self.combo_small.currentText(),
            'site_name': self.input_site_name.text(),
            'url': self.input_url.text()
        }
    
    def accept(self):
        """확인 버튼 클릭 시 유효성 검사"""
        data = self.get_data()
        if not data['category_large'] or not data['site_name'] or not data['url']:
            QMessageBox.warning(self, "입력 오류", "대분류, 사이트명, URL은 필수입니다!")
            return
        super().accept()

# ============================================================
# 상품 등록/수정 다이얼로그
# ============================================================
class ProductDialog(QDialog):
    """상품 등록 및 수정 다이얼로그"""
    
    def __init__(self, db_manager, product_data=None, parent=None):
        super().__init__(parent)
        self.db = db_manager
        self.product_data = product_data  # 수정 시 기존 데이터
        self.init_ui()
    
    def init_ui(self):
        self.setWindowTitle("상품 등록" if not self.product_data else "상품 수정")
        self.setMinimumWidth(500)
        
        layout = QVBoxLayout(self)
        form_layout = QFormLayout()
        
        # 카테고리 대분류
        self.combo_large = QComboBox()
        self.combo_large.setEditable(True)
        self.combo_large.addItems(self.db.get_unique_categories('large'))
        form_layout.addRow("대분류:", self.combo_large)
        
        # 카테고리 중분류
        self.combo_medium = QComboBox()
        self.combo_medium.setEditable(True)
        self.combo_medium.addItems(self.db.get_unique_categories('medium'))
        form_layout.addRow("중분류:", self.combo_medium)
        
        # 카테고리 소분류
        self.combo_small = QComboBox()
        self.combo_small.setEditable(True)
        self.combo_small.addItems(self.db.get_unique_categories('small'))
        form_layout.addRow("소분류:", self.combo_small)
        
        # 상품명
        self.input_name = QLineEdit()
        self.input_name.setPlaceholderText("예: 남성용 기모 후드티")
        form_layout.addRow("상품명*:", self.input_name)
        
        # 판매처
        self.input_vendor = QLineEdit()
        self.input_vendor.setPlaceholderText("예: 쿠팡")
        form_layout.addRow("판매처*:", self.input_vendor)
        
        # 가격 (QLineEdit로 변경!)
        self.input_price = QLineEdit()
        self.input_price.setPlaceholderText("예: 25000")
        form_layout.addRow("💰 가격*:", self.input_price)

        # 택배비 (새로 추가!)
        self.input_delivery_fee = QLineEdit()
        self.input_delivery_fee.setPlaceholderText("예: 3000 (무료배송이면 0)")
        self.input_delivery_fee.setText("0")
        form_layout.addRow("📦 택배비:", self.input_delivery_fee)
        
        # URL
        self.input_url = QLineEdit()
        self.input_url.setPlaceholderText("https://...")
        form_layout.addRow("URL:", self.input_url)
        
        # CSS Selector
        selector_layout = QHBoxLayout()
        self.input_selector = QLineEdit()
        self.input_selector.setPlaceholderText("예: .price-value, #product_price")
        btn_selector_help = QPushButton("❓")
        btn_selector_help.setMaximumWidth(30)
        btn_selector_help.clicked.connect(self.show_selector_help)
        selector_layout.addWidget(self.input_selector)
        selector_layout.addWidget(btn_selector_help)
        form_layout.addRow("CSS Selector:", selector_layout)
        
        # 비고
        self.input_memo = QTextEdit()
        self.input_memo.setMaximumHeight(60)
        self.input_memo.setPlaceholderText("메모 입력...")
        form_layout.addRow("비고:", self.input_memo)
        
        layout.addLayout(form_layout)
        
        # 버튼
        button_box = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        button_box.accepted.connect(self.accept)
        button_box.rejected.connect(self.reject)
        layout.addWidget(button_box)
        
        # 기존 데이터 로드 (수정 모드)
        if self.product_data:
            self.load_product_data()
    
    def load_product_data(self):
        """기존 상품 데이터 로드 (수정 모드)"""
        if self.product_data:
            self.combo_large.setCurrentText(self.product_data[1])
            self.combo_medium.setCurrentText(self.product_data[2])
            self.combo_small.setCurrentText(self.product_data[3])
            self.input_name.setText(self.product_data[4])
            self.input_vendor.setText(self.product_data[5])
            self.input_price.setText(str(self.product_data[6]))  # 수정!
            self.input_url.setText(self.product_data[7] or "")
            self.input_selector.setText(self.product_data[8] or "")
            self.input_memo.setPlainText(self.product_data[9] or "")
            
            # 택배비는 히스토리에서 가져오기 (선택사항)
            self.input_delivery_fee.setText("0")   
    
    def show_selector_help(self):
        """CSS Selector 도움말"""
        help_text = """
CSS Selector 찾는 방법:

1. 크롬 브라우저로 상품 페이지 접속
2. 가격 부분에서 마우스 우클릭 → '검사'
3. HTML 코드에서 가격 요소 우클릭
4. 'Copy' → 'Copy selector' 선택
5. 복사된 selector를 여기에 붙여넣기

예시:
- .price-value
- #product_price
- span.sale-price > strong
        """
        QMessageBox.information(self, "CSS Selector 도움말", help_text.strip())
    
    def get_data(self):
        """입력된 데이터 반환"""
        # 가격 파싱
        try:
            price = int(self.input_price.text().strip().replace(',', ''))
        except ValueError:
            price = 0
        
        # 택배비 파싱
        try:
            delivery_fee = int(self.input_delivery_fee.text().strip().replace(',', ''))
        except ValueError:
            delivery_fee = 0
        
        return {
            'category_large': self.combo_large.currentText().strip(),
            'category_medium': self.combo_medium.currentText().strip(),
            'category_small': self.combo_small.currentText().strip(),
            'product_name': self.input_name.text().strip(),
            'vendor': self.input_vendor.text().strip(),
            'price': price,
            'delivery_fee': delivery_fee,
            'url': self.input_url.text().strip(),
            'css_selector': self.input_selector.text().strip(),
            'memo': self.input_memo.toPlainText().strip()
        }
    
    def accept(self):
        """확인 버튼 클릭 시 유효성 검사"""
        data = self.get_data()
        if not data['product_name'] or not data['vendor'] or data['price'] <= 0:
            QMessageBox.warning(self, "입력 오류", "상품명, 판매처, 가격은 필수입니다!")
            return
        super().accept()


# ============================================================
# 메인 윈도우
# ============================================================
class MarketResearchApp(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("시장조사 및 매입 관리 툴 v2.0")
        self.resize(1400, 900)
        
        # DB 초기화
        self.db = DatabaseManager()
        
        # 상태 관리
        self.current_product_id = None
        
        self.init_ui()
        self.load_initial_data()
    
    def init_ui(self):
        """UI 초기화"""
        # 메인 위젯
        main_widget = QWidget()
        self.setCentralWidget(main_widget)
        
        main_layout = QVBoxLayout(main_widget)
        main_layout.setContentsMargins(0, 0, 0, 0)
        
        # 탭 위젯 생성
        self.tabs = QTabWidget()
        self.tabs.setStyleSheet("""
            QTabWidget::pane {
                border: 1px solid #cccccc;
            }
            QTabBar::tab {
                background: #f0f0f0;
                padding: 10px 20px;
                margin-right: 2px;
                font-size: 12px;
                font-weight: bold;
            }
            QTabBar::tab:selected {
                background: #4f46e5;
                color: white;
            }
        """)
        
        # 홈 탭
        self.home_tab = QWidget()
        self.setup_home_tab()
        self.tabs.addTab(self.home_tab, "🏠 홈")
        
        # 관리 탭
        self.manage_tab = QWidget()
        self.setup_manage_tab()
        self.tabs.addTab(self.manage_tab, "⚙️ 관리")
        
        main_layout.addWidget(self.tabs)
    
    # ========================================
    # 홈 탭 설정
    # ========================================
    def setup_home_tab(self):
        """홈 탭 구성 (기존 3분할 구조)"""
        layout = QHBoxLayout(self.home_tab)
        layout.setContentsMargins(0, 0, 0, 0)
        
        splitter = QSplitter(Qt.Orientation.Horizontal)
        
        # [1구역] 좌측: 상품 관리
        self.panel_left = QWidget()
        self.setup_left_panel()
        splitter.addWidget(self.panel_left)
        
        # [2구역] 중앙: 히스토리
        self.panel_center = QWidget()
        self.setup_center_panel()
        splitter.addWidget(self.panel_center)
        
        # [3구역] 우측: 그래프 및 즐겨찾기
        self.panel_right = QWidget()
        self.setup_right_panel()
        splitter.addWidget(self.panel_right)
        
        splitter.setSizes([300, 540, 360])
        layout.addWidget(splitter)
    
    def setup_left_panel(self):
        """[1구역] 좌측 패널 - 상품 관리"""
        layout = QVBoxLayout(self.panel_left)
        layout.setContentsMargins(10, 10, 10, 10)
        
        # 타이틀
        title = QLabel("🛍️ 상품 관리")
        title.setFont(QFont("Malgun Gothic", 12, QFont.Weight.Bold))
        layout.addWidget(title)
        
        # 버튼 그룹
        btn_layout = QHBoxLayout()
        self.btn_add_product = QPushButton("➕ 상품 등록")
        self.btn_add_product.setStyleSheet("""
            QPushButton {
                background-color: #16a34a;
                color: white;
                font-weight: bold;
                padding: 8px;
                border-radius: 4px;
            }
            QPushButton:hover {
                background-color: #15803d;
            }
        """)
        self.btn_add_product.clicked.connect(self.add_product)
        btn_layout.addWidget(self.btn_add_product)
        layout.addLayout(btn_layout)
        
        # 검색창
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("🔍 상품명 또는 판매처 검색...")
        self.search_input.textChanged.connect(self.refresh_product_list)
        layout.addWidget(self.search_input)
        
        # 상품 리스트
        self.product_list_widget = QListWidget()
        self.product_list_widget.itemClicked.connect(self.on_product_clicked)

        # 우클릭 메뉴 활성화 (새로 추가!)
        self.product_list_widget.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.product_list_widget.customContextMenuRequested.connect(self.show_product_context_menu)

        layout.addWidget(self.product_list_widget)
    
    def setup_center_panel(self):
        """[2구역] 중앙 패널 - 히스토리"""
        layout = QVBoxLayout(self.panel_center)
        layout.setContentsMargins(10, 10, 10, 10)
        
        # 헤더
        header_layout = QHBoxLayout()
        self.history_title = QLabel("🕒 가격 변동 히스토리")
        self.history_title.setFont(QFont("Malgun Gothic", 12, QFont.Weight.Bold))
        
        self.btn_crawl = QPushButton("🔄 전체 크롤링")
        self.btn_crawl.setStyleSheet("""
            QPushButton {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                    stop:0 #4f46e5, stop:1 #7c3aed);
                color: white;
                font-weight: bold;
                padding: 8px 15px;
                border-radius: 4px;
            }
            QPushButton:hover {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                    stop:0 #4338ca, stop:1 #6d28d9);
            }
        """)
        self.btn_crawl.clicked.connect(self.crawl_all_products)
        
        header_layout.addWidget(self.history_title)
        header_layout.addStretch()
        header_layout.addWidget(self.btn_crawl)
        layout.addLayout(header_layout)
        
        # 테이블
        self.history_table = QTableWidget()
        self.history_table.setColumnCount(6)
        self.history_table.setHorizontalHeaderLabels(["날짜", "시간", "매입처", "가격", "택배비", "변동폭"])
        self.history_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.history_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.history_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        
        # 우클릭 메뉴 활성화
        self.history_table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.history_table.customContextMenuRequested.connect(self.show_history_context_menu)

        layout.addWidget(self.history_table)
    
    def setup_right_panel(self):
        """[3구역] 우측 패널 - 그래프 및 즐겨찾기"""
        layout = QVBoxLayout(self.panel_right)
        layout.setContentsMargins(10, 10, 10, 10)
        
        right_splitter = QSplitter(Qt.Orientation.Vertical)
        
        # 1. 그래프 영역
        graph_widget = QWidget()
        graph_layout = QVBoxLayout(graph_widget)
        graph_layout.setContentsMargins(0, 0, 0, 0)
        
        graph_title = QLabel("📈 가격 추이 그래프")
        graph_title.setFont(QFont("Malgun Gothic", 12, QFont.Weight.Bold))
        graph_layout.addWidget(graph_title)
        
        self.figure = plt.Figure(figsize=(5, 4), dpi=100)
        self.canvas = FigureCanvas(self.figure)
        self.ax = self.figure.add_subplot(111)
        graph_layout.addWidget(self.canvas)
        
        right_splitter.addWidget(graph_widget)
        
        # 2. 즐겨찾기 영역
        bookmark_widget = QWidget()
        bookmark_layout = QVBoxLayout(bookmark_widget)
        bookmark_layout.setContentsMargins(0, 10, 0, 0)
        
        # 헤더 (타이틀 + 추가 버튼)
        bm_header_layout = QHBoxLayout()
        bm_title = QLabel("🔖 매입처 즐겨찾기")
        bm_title.setFont(QFont("Malgun Gothic", 12, QFont.Weight.Bold))
        
        btn_add_bookmark = QPushButton("➕ 추가")
        btn_add_bookmark.setStyleSheet("""
            QPushButton {
                background-color: #10b981;
                color: white;
                font-weight: bold;
                padding: 5px 12px;
                border-radius: 4px;
            }
            QPushButton:hover {
                background-color: #059669;
            }
        """)
        btn_add_bookmark.clicked.connect(self.add_bookmark)
        
        bm_header_layout.addWidget(bm_title)
        bm_header_layout.addStretch()
        bm_header_layout.addWidget(btn_add_bookmark)
        bookmark_layout.addLayout(bm_header_layout)
        
        self.tree = QTreeWidget()
        self.tree.setHeaderHidden(True)
        self.tree.itemDoubleClicked.connect(self.on_bookmark_double_clicked)
        
        # 우클릭 메뉴 활성화
        self.tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self.show_bookmark_context_menu)
        
        bookmark_layout.addWidget(self.tree)
        
        right_splitter.addWidget(bookmark_widget)
        right_splitter.setSizes([300, 300])
        
        layout.addWidget(right_splitter)
    
    # ========================================
    # 관리 탭 설정
    # ========================================
    def setup_manage_tab(self):
        """관리 탭 구성"""
        layout = QVBoxLayout(self.manage_tab)
        layout.setContentsMargins(20, 20, 20, 20)
        
        title = QLabel("⚙️ 데이터 관리")
        title.setFont(QFont("Malgun Gothic", 16, QFont.Weight.Bold))
        layout.addWidget(title)
        
        # 상품 관리 테이블
        manage_title = QLabel("📦 등록된 상품 목록")
        manage_title.setFont(QFont("Malgun Gothic", 12, QFont.Weight.Bold))
        layout.addWidget(manage_title)
        
        self.manage_table = QTableWidget()
        self.manage_table.setColumnCount(7)
        self.manage_table.setHorizontalHeaderLabels([
            "ID", "카테고리", "상품명", "판매처", "현재가", "URL", "비고"
        ])
        self.manage_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        layout.addWidget(self.manage_table)
        
        # 버튼 그룹
        btn_layout = QHBoxLayout()
        
        btn_edit = QPushButton("✏️ 수정")
        btn_edit.clicked.connect(self.edit_product)
        btn_layout.addWidget(btn_edit)
        
        btn_delete = QPushButton("🗑️ 삭제")
        btn_delete.setStyleSheet("background-color: #dc2626; color: white; font-weight: bold;")
        btn_delete.clicked.connect(self.delete_product)
        btn_layout.addWidget(btn_delete)
        
        btn_refresh = QPushButton("🔄 새로고침")
        btn_refresh.clicked.connect(self.refresh_manage_table)
        btn_layout.addWidget(btn_refresh)
        
        btn_layout.addStretch()
        layout.addLayout(btn_layout)
    
    # ========================================
    # 데이터 로드 및 갱신
    # ========================================
    def load_initial_data(self):
        """초기 데이터 로드"""
        self.refresh_product_list()
        self.refresh_bookmarks()
        self.refresh_manage_table()
    
    def refresh_product_list(self):
        """상품 리스트 갱신"""
        self.product_list_widget.clear()
        search_term = self.search_input.text()
        products = self.db.get_all_products(search_term)
        
        for p in products:
            p_id, cat_l, cat_m, cat_s, name, vendor, price = p[0], p[1], p[2], p[3], p[4], p[5], p[6]
            
            # 카테고리 표시
            category = cat_l
            if cat_m:
                category += f" > {cat_m}"
            if cat_s:
                category += f" > {cat_s}"
            
            item_text = f"[{category}]\n{name}\n{vendor} | {price:,}원"
            item = QListWidgetItem(item_text)
            item.setData(Qt.ItemDataRole.UserRole, p_id)
            self.product_list_widget.addItem(item)
            
            if p_id == self.current_product_id:
                item.setSelected(True)
    
    def refresh_bookmarks(self):
        """즐겨찾기 트리 갱신"""
        self.tree.clear()
        bookmarks = self.db.get_all_bookmarks()
        self.load_bookmark_tree(bookmarks, self.tree)
    
    def load_bookmark_tree(self, data, parent_widget):
        """재귀적으로 즐겨찾기 트리 로드"""
        for key, value in data.items():
            if isinstance(value, dict):
                # 폴더
                item = QTreeWidgetItem(parent_widget)
                item.setText(0, key)
                item.setIcon(0, QApplication.style().standardIcon(
                    QApplication.style().StandardPixmap.SP_DirIcon))
                self.load_bookmark_tree(value, item)
            elif isinstance(value, list):
                # 사이트 목록
                for site_name, url in value:
                    item = QTreeWidgetItem(parent_widget)
                    item.setText(0, site_name)
                    item.setData(0, Qt.ItemDataRole.UserRole, url)
                    item.setIcon(0, QApplication.style().standardIcon(
                        QApplication.style().StandardPixmap.SP_FileIcon))
    
    def refresh_manage_table(self):
        """관리 탭 테이블 갱신"""
        products = self.db.get_all_products()
        self.manage_table.setRowCount(len(products))
        
        for i, p in enumerate(products):
            p_id, cat_l, cat_m, cat_s, name, vendor, price, url, selector, memo = p[0:10]
            
            category = cat_l
            if cat_m:
                category += f" > {cat_m}"
            if cat_s:
                category += f" > {cat_s}"
            
            self.manage_table.setItem(i, 0, QTableWidgetItem(str(p_id)))
            self.manage_table.setItem(i, 1, QTableWidgetItem(category))
            self.manage_table.setItem(i, 2, QTableWidgetItem(name))
            self.manage_table.setItem(i, 3, QTableWidgetItem(vendor))
            self.manage_table.setItem(i, 4, QTableWidgetItem(f"{price:,}원"))
            self.manage_table.setItem(i, 5, QTableWidgetItem(url or "-"))
            self.manage_table.setItem(i, 6, QTableWidgetItem(memo or "-"))
    
    def on_product_clicked(self, item):
        """상품 클릭 이벤트"""
        self.current_product_id = item.data(Qt.ItemDataRole.UserRole)
        self.update_history_and_graph()

    def show_product_context_menu(self, position):
        """상품 리스트 우클릭 메뉴"""
        # 선택된 아이템 확인
        item = self.product_list_widget.itemAt(position)
        if not item:
            return
        
        # 상품 ID 가져오기
        product_id = item.data(Qt.ItemDataRole.UserRole)
        if not product_id:
            return
        
        # 컨텍스트 메뉴 생성
        from PyQt6.QtWidgets import QMenu
        menu = QMenu(self)
        
        # 메뉴 아이템 추가
        action_edit = menu.addAction("✏️ 수정")
        action_delete = menu.addAction("🗑️ 삭제")
        
        # 메뉴 표시 및 선택된 액션 처리
        action = menu.exec(self.product_list_widget.mapToGlobal(position))
        
        if action == action_edit:
            self.edit_product_from_list(product_id)
        elif action == action_delete:
            self.delete_product_from_list(product_id)
    
    def edit_product_from_list(self, product_id):
        """상품 수정 (리스트에서 우클릭)"""
        products = self.db.get_all_products()
        product = next((p for p in products if p[0] == product_id), None)
        
        if not product:
            QMessageBox.warning(self, "오류", "상품을 찾을 수 없습니다.")
            return
        
        dialog = ProductDialog(self.db, product_data=product, parent=self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            data = dialog.get_data() # 사용자가 수정한 데이터(택배비 포함) 가져오기 [cite: 116, 117]
            
            # 1. 기본 상품 정보 업데이트 [cite: 163]
            self.db.update_product(product_id, data)
            
            # 2. 변경된 정보를 히스토리에도 즉시 기록 (핵심!)
            self.db.add_price_history(
                product_id, 
                data['price'], 
                data['delivery_fee'], 
                data['vendor']
            )
            
            # 3. 화면 UI 갱신 [cite: 163]
            self.refresh_product_list()
            self.refresh_manage_table()
            self.update_history_and_graph() # 히스토리 테이블과 그래프 즉시 갱신
            
            QMessageBox.information(self, "성공", "상품 정보와 히스토리가 업데이트되었습니다!")
    
    def delete_product_from_list(self, product_id):
        """상품 삭제 (리스트에서 우클릭)"""
        # 확인 메시지
        reply = QMessageBox.question(
            self,
            "삭제 확인",
            "정말 이 상품을 삭제하시겠습니까?\n(히스토리도 함께 삭제됩니다)",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        
        if reply == QMessageBox.StandardButton.Yes:
            self.db.delete_product(product_id)
            self.refresh_product_list()
            self.refresh_manage_table()
            
            # 현재 선택된 상품이면 초기화
            if self.current_product_id == product_id:
                self.current_product_id = None
                self.history_table.setRowCount(0)
                self.ax.clear()
                self.canvas.draw()
            
            QMessageBox.information(self, "성공", "상품이 삭제되었습니다!")

    def update_history_and_graph(self):
        """히스토리 테이블 및 그래프 갱신"""
        if not self.current_product_id:
            return
        
        # 상품 정보
        products = self.db.get_all_products()
        product = next((p for p in products if p[0] == self.current_product_id), None)
        if not product:
            return
        
        self.history_title.setText(f"🕒 히스토리: {product[4]}")
        
        # 히스토리 데이터
        histories = self.db.get_price_history(self.current_product_id)
        self.history_table.setRowCount(len(histories))
        
        for i, h in enumerate(histories):
            # 데이터 언패킹 (7개)
            if len(h) == 7:
                h_id, p_id, date, time, price, delivery_fee, vendor = h
            elif len(h) == 6:
                # 구버전 호환 (delivery_fee 없음)
                h_id, p_id, date, time, price, vendor = h
                delivery_fee = 0
            else:
                continue
            
            # 날짜 (히스토리 ID 저장)
            date_item = QTableWidgetItem(date)
            date_item.setData(Qt.ItemDataRole.UserRole, h_id)
            self.history_table.setItem(i, 0, date_item)
            
            # 시간
            self.history_table.setItem(i, 1, QTableWidgetItem(time))
            
            # 매입처
            self.history_table.setItem(i, 2, QTableWidgetItem(vendor or "-"))
            
            # 가격
            price_item = QTableWidgetItem(f"{price:,}원")
            price_item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            self.history_table.setItem(i, 3, price_item)
            
            # 택배비 (새로!)
            if delivery_fee > 0:
                delivery_text = f"{delivery_fee:,}원"
                delivery_color = QColor("black")
            else:
                delivery_text = "무료"
                delivery_color = QColor(22, 163, 74)
            
            delivery_item = QTableWidgetItem(delivery_text)
            delivery_item.setForeground(delivery_color)
            delivery_item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            self.history_table.setItem(i, 4, delivery_item)
            
            # 변동폭 (컬럼 5로 이동!)
            diff_text = "-"
            diff_color = QColor("black")
            if i < len(histories) - 1:
                prev_price = histories[i + 1][4]
                diff = price - prev_price
                if diff > 0:
                    diff_text = f"▲ {diff:,}"
                    diff_color = QColor("red")
                elif diff < 0:
                    diff_text = f"▼ {abs(diff):,}"
                    diff_color = QColor("blue")
            
            diff_item = QTableWidgetItem(diff_text)
            diff_item.setForeground(diff_color)
            diff_item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            self.history_table.setItem(i, 5, diff_item)
        
        # 그래프 업데이트
        sorted_histories = sorted(histories, key=lambda x: (x[2], x[3]))
        if sorted_histories:
            dates = [f"{h[2]}\n{h[3][:5]}" for h in sorted_histories]
            prices = [h[4] for h in sorted_histories]
            
            self.ax.clear()
            self.ax.plot(dates, prices, marker='o', linestyle='-', color='#4f46e5', linewidth=2)
            self.ax.set_title("최근 가격 추이", fontsize=11, fontweight='bold')
            self.ax.grid(True, linestyle='--', alpha=0.4)
            self.ax.tick_params(axis='x', rotation=45, labelsize=8)
            self.figure.tight_layout()
            self.canvas.draw()
    
    # ========================================
    # 이벤트 핸들러
    # ========================================
    def on_product_clicked(self, item):
        """상품 클릭 이벤트"""
        self.current_product_id = item.data(Qt.ItemDataRole.UserRole)
        self.update_history_and_graph()
    
    def on_bookmark_double_clicked(self, item, column):
        """즐겨찾기 더블클릭 - 브라우저 열기"""
        url = item.data(0, Qt.ItemDataRole.UserRole)
        if url:
            import webbrowser
            webbrowser.open(url)
    
    def add_product(self):
        """상품 등록"""
        dialog = ProductDialog(self.db, parent=self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            data = dialog.get_data()
            self.db.add_product(data)
            self.refresh_product_list()
            self.refresh_manage_table()
            QMessageBox.information(self, "성공", "상품이 등록되었습니다!")
    
    def edit_product(self):
        """관리 탭에서 상품 수정"""
        current_row = self.manage_table.currentRow()
        if current_row < 0:
            QMessageBox.warning(self, "선택 오류", "수정할 상품을 선택하세요!")
            return
            
        product_id = int(self.manage_table.item(current_row, 0).text()) [cite: 183]
        products = self.db.get_all_products()
        product = next((p for p in products if p[0] == product_id), None)
        
        if product:
            dialog = ProductDialog(self.db, product_data=product, parent=self)
            if dialog.exec() == QDialog.DialogCode.Accepted:
                data = dialog.get_data()
                
                # 1. 기본 정보 업데이트 [cite: 184]
                self.db.update_product(product_id, data)
                
                # 2. 히스토리에 변경 사항 기록
                self.db.add_price_history(
                    product_id, 
                    data['price'], 
                    data['delivery_fee'], 
                    data['vendor']
                )
                
                self.refresh_product_list()
                self.refresh_manage_table()
                self.update_history_and_graph()
                QMessageBox.information(self, "성공", "수정 사항이 히스토리에 반영되었습니다!")
    
    def delete_product(self):
        """상품 삭제"""
        current_row = self.manage_table.currentRow()
        if current_row < 0:
            QMessageBox.warning(self, "선택 오류", "삭제할 상품을 선택하세요!")
            return
        
        product_id = int(self.manage_table.item(current_row, 0).text())
        product_name = self.manage_table.item(current_row, 2).text()
        
        reply = QMessageBox.question(
            self, "삭제 확인",
            f"'{product_name}' 상품을 삭제하시겠습니까?\n(히스토리도 함께 삭제됩니다)",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        
        if reply == QMessageBox.StandardButton.Yes:
            self.db.delete_product(product_id)
            self.refresh_product_list()
            self.refresh_manage_table()
            QMessageBox.information(self, "성공", "상품이 삭제되었습니다!")
    
    def crawl_all_products(self):
        """전체 상품 크롤링"""
        products = self.db.get_all_products()
        
        # URL과 Selector가 있는 상품만 필터링
        crawl_targets = [
            (p[0], p[7], p[8], p[5]) for p in products if p[7] and p[8]
        ]
        
        if not crawl_targets:
            QMessageBox.information(self, "알림", "크롤링 가능한 상품이 없습니다.\n(URL과 CSS Selector가 모두 있어야 합니다)")
            return
        
        # 크롤링 모드 선택 다이얼로그
        msg = QMessageBox(self)
        msg.setWindowTitle("크롤링 모드 선택")
        msg.setText("어떤 방식으로 크롤링하시겠습니까?")
        msg.setInformativeText(
            "🚀 빠른 모드: 일반 사이트용 (빠름, 일부 사이트 차단됨)\n"
            "🔧 Selenium: 네이버/쿠팡 등 (느림, 거의 모든 사이트 가능)"
        )
        
        btn_fast = msg.addButton("🚀 빠른 모드", QMessageBox.ButtonRole.AcceptRole)
        btn_selenium = msg.addButton("🔧 Selenium", QMessageBox.ButtonRole.ActionRole)
        msg.addButton("취소", QMessageBox.ButtonRole.RejectRole)
        
        msg.exec()
        
        use_selenium = False
        if msg.clickedButton() == btn_selenium:
            use_selenium = True
        elif msg.clickedButton() != btn_fast:
            return  # 취소
        
        # 프로그레스 다이얼로그
        progress = QProgressDialog("크롤링 준비 중...", "취소", 0, 100, self)
        progress.setWindowTitle("가격 크롤링")
        progress.setWindowModality(Qt.WindowModality.WindowModal)
        progress.setMinimumDuration(0)
        
        # 워커 스레드 시작
        self.crawl_worker = CrawlWorker(crawl_targets, use_selenium=use_selenium)
        self.crawl_worker.progress.connect(lambda val, msg: (
            progress.setValue(val),
            progress.setLabelText(msg)
        ))
        self.crawl_worker.finished.connect(lambda results: self.on_crawl_finished(results, progress))
        self.crawl_worker.start()

    def on_crawl_finished(self, results, progress_dialog):
        """크롤링 완료 처리"""
        progress_dialog.close()
        success_count = 0
        fail_count = 0
        
        for p_id, price, success, debug_info in results:
            if success:
                # 현재 저장된 상품 정보 불러오기 
                products = self.db.get_all_products()
                product = next((p for p in products if p[0] == p_id), None)
                
                if product:
                    # 히스토리 추가 시 기존 매입처와 가격을 기록 (택배비 포함)
                    # 주의: 현재 상품 테이블 구조에 택배비 컬럼이 별도로 없으므로, 
                    # 가장 최근 히스토리에서 택배비를 가져오거나 기본값 0을 사용합니다.
                    
                    # 1. 히스토리 추가 
                    self.db.add_price_history(p_id, price, 0, product[5]) 
                    
                    # 2. 상품 테이블의 현재가 업데이트 [cite: 198]
                    data = {
                        'category_large': product[1],
                        'category_medium': product[2],
                        'category_small': product[3],
                        'product_name': product[4],
                        'vendor': product[5],
                        'price': price,
                        'url': product[7],
                        'css_selector': product[8],
                        'memo': product[9]
                    }
                    self.db.update_product(p_id, data)
                success_count += 1
            else:
                fail_count += 1
        
        self.refresh_product_list()
        self.update_history_and_graph()
        
        # 결과 메시지
        msg = QMessageBox(self)
        msg.setWindowTitle("크롤링 완료")
        msg.setIcon(QMessageBox.Icon.Information)
        msg.setText(f"✅ 성공: {success_count}개\n❌ 실패: {fail_count}개")
        
        # 실패가 있으면 디버그 버튼 추가
        if fail_count > 0:
            msg.setInformativeText("실패 원인을 확인하시겠습니까?")
            debug_btn = msg.addButton("🔍 상세보기", QMessageBox.ButtonRole.ActionRole)
            msg.addButton("닫기", QMessageBox.ButtonRole.RejectRole)
            msg.exec()
            
            # 디버그 버튼 클릭 시
            if msg.clickedButton() == debug_btn:
                debug_dialog = CrawlDebugDialog(results, self)
                debug_dialog.exec()
        else:
            msg.exec()

    def show_history_context_menu(self, position):
        """히스토리 테이블 우클릭 메뉴"""
        # 클릭한 행 확인
        row = self.history_table.rowAt(position.y())
        if row < 0:
            return  # 빈 공간 클릭 시 무시
        
        # 컨텍스트 메뉴 생성
        from PyQt6.QtWidgets import QMenu
        menu = QMenu(self)
        
        # 메뉴 스타일 설정
        menu.setStyleSheet("""
            QMenu {
                background-color: #ffffff;
                border: 1px solid #d1d5db;
                border-radius: 4px;
                padding: 4px;
            }
            QMenu::item {
                padding: 8px 24px;
                border-radius: 4px;
                color: #1f2937;
            }
            QMenu::item:selected {
                background-color: #3b82f6;
                color: white;
            }
            QMenu::item:hover {
                background-color: #3b82f6;
                color: white;
            }
        """)
        
        delete_action = menu.addAction("🗑️ 이 히스토리 삭제")
        delete_action.triggered.connect(lambda: self.delete_history_item(row))
        
        # 메뉴 표시
        menu.exec(self.history_table.viewport().mapToGlobal(position))
    
    def delete_history_item(self, row):
        """히스토리 항목 삭제"""
        # 히스토리 ID 가져오기
        date_item = self.history_table.item(row, 0)
        if not date_item:
            return
        
        history_id = date_item.data(Qt.ItemDataRole.UserRole)
        if not history_id:
            QMessageBox.warning(self, "오류", "히스토리 ID를 찾을 수 없습니다.")
            return
        
        # 삭제 확인
        date = date_item.text()
        time = self.history_table.item(row, 1).text()
        price = self.history_table.item(row, 3).text()
        
        reply = QMessageBox.question(
            self, "삭제 확인",
            f"이 히스토리를 삭제하시겠습니까?\n\n"
            f"날짜: {date} {time}\n"
            f"가격: {price}",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        
        if reply == QMessageBox.StandardButton.Yes:
            # DB에서 삭제
            self.db.delete_price_history(history_id)
            
            # 화면 갱신
            self.update_history_and_graph()
            
            QMessageBox.information(self, "완료", "히스토리가 삭제되었습니다.")

    def add_bookmark(self):
        """즐겨찾기 추가"""
        dialog = BookmarkDialog(self.db, parent=self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            data = dialog.get_data()
            self.db.add_bookmark(data)
            self.refresh_bookmarks()
            QMessageBox.information(self, "완료", "즐겨찾기가 추가되었습니다!")

    def show_bookmark_context_menu(self, position):
        """즐겨찾기 트리 우클릭 메뉴"""
        item = self.tree.itemAt(position)
        if not item:
            return
        
        # URL이 있는 항목만 삭제 가능 (폴더는 제외)
        url = item.data(0, Qt.ItemDataRole.UserRole)
        if not url:
            return
        
        # 컨텍스트 메뉴 생성
        from PyQt6.QtWidgets import QMenu
        menu = QMenu(self)
        
        # 메뉴 스타일 설정
        menu.setStyleSheet("""
            QMenu {
                background-color: #ffffff;
                border: 1px solid #d1d5db;
                border-radius: 4px;
                padding: 4px;
            }
            QMenu::item {
                padding: 8px 24px;
                border-radius: 4px;
                color: #1f2937;
            }
            QMenu::item:selected {
                background-color: #ef4444;
                color: white;
            }
            QMenu::item:hover {
                background-color: #ef4444;
                color: white;
            }
        """)
        
        delete_action = menu.addAction("🗑️ 즐겨찾기 삭제")
        delete_action.triggered.connect(lambda: self.delete_bookmark_item(item))
        
        # 메뉴 표시
        menu.exec(self.tree.viewport().mapToGlobal(position))
    
    def delete_bookmark_item(self, item):
        """즐겨찾기 항목 삭제"""
        url = item.data(0, Qt.ItemDataRole.UserRole)
        if not url:
            return
        
        site_name = item.text(0)
        
        # 삭제 확인
        reply = QMessageBox.question(
            self, "삭제 확인",
            f"'{site_name}' 즐겨찾기를 삭제하시겠습니까?\n\nURL: {url}",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        
        if reply == QMessageBox.StandardButton.Yes:
            # DB에서 ID 찾아서 삭제
            bookmark_id = self.db.get_bookmark_by_url(url)
            if bookmark_id:
                self.db.delete_bookmark(bookmark_id)
                self.refresh_bookmarks()
                QMessageBox.information(self, "완료", "즐겨찾기가 삭제되었습니다!")
            else:
                QMessageBox.warning(self, "오류", "즐겨찾기를 찾을 수 없습니다.")
# ============================================================
# 메인 실행
# ============================================================
if __name__ == '__main__':
    app = QApplication(sys.argv)
    
    # 전체 폰트 설정
    font = QFont("Malgun Gothic", 10)
    app.setFont(font)
    
    # 스타일시트
    app.setStyleSheet("""
        QMainWindow {
            background-color: #f9fafb;
        }
        QWidget {
            background-color: white;
        }
        QPushButton {
            padding: 6px 12px;
            border-radius: 4px;
            border: 1px solid #d1d5db;
            background-color: #f3f4f6;
        }
        QPushButton:hover {
            background-color: #e5e7eb;
        }
        QLineEdit, QComboBox, QSpinBox {
            padding: 6px;
            border: 1px solid #d1d5db;
            border-radius: 4px;
        }
        QTableWidget {
            gridline-color: #e5e7eb;
            border: 1px solid #d1d5db;
        }
        QHeaderView::section {
            background-color: #f3f4f6;
            padding: 8px;
            border: none;
            font-weight: bold;
        }
    """)
    
    window = MarketResearchApp()
    window.show()
    sys.exit(app.exec())