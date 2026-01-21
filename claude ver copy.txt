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

import undetected_chromedriver as uc

# PyQt6 라이브러리 임포트
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QSplitter, QListWidget, QListWidgetItem, QLabel, QLineEdit,
    QPushButton, QTableWidget, QTableWidgetItem, QHeaderView,
    QTreeWidget, QTreeWidgetItem, QMessageBox, QFrame, QTabWidget,
    QDialog, QComboBox, QTextEdit, QFormLayout, QDialogButtonBox,
    QProgressDialog, QSpinBox, QCheckBox, QSizePolicy
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal, QTimer  # QTimer 추가!
from PyQt6.QtGui import QFont, QColor, QShortcut, QKeySequence  # QShortcut, QKeySequence 추가!
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
                vendor TEXT,
                FOREIGN KEY (product_id) REFERENCES products(id)
            )
        ''')
        
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

        # 설정 테이블
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT
            )
        ''')

        # 검색 히스토리 테이블
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS search_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                site TEXT NOT NULL,
                product_name TEXT NOT NULL,
                price INTEGER NOT NULL,
                url TEXT NOT NULL,
                viewed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
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
        now = datetime.now()
        cursor.execute('''
            INSERT INTO price_history (product_id, crawled_date, crawled_time, price, vendor)
            VALUES (?, ?, ?, ?, ?)
        ''', (product_id, now.strftime('%Y-%m-%d'), now.strftime('%H:%M:%S'), 
              data['price'], data['vendor']))
        
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
    def add_price_history(self, product_id, price, vendor=None):
        """가격 히스토리 추가"""
        conn = self.get_connection()
        cursor = conn.cursor()
        now = datetime.now()
        cursor.execute('''
            INSERT INTO price_history (product_id, crawled_date, crawled_time, price, vendor)
            VALUES (?, ?, ?, ?, ?)
        ''', (product_id, now.strftime('%Y-%m-%d'), now.strftime('%H:%M:%S'), price, vendor))
        conn.commit()
        conn.close()
    
    def get_price_history(self, product_id):
        """특정 상품의 가격 히스토리 조회"""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute('''
            SELECT * FROM price_history 
            WHERE product_id=? 
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
    def get_setting(self, key):
        """설정 값 가져오기"""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute('SELECT value FROM settings WHERE key=?', (key,))
        result = cursor.fetchone()
        conn.close()
        return result[0] if result else None
    
    def set_setting(self, key, value):
        """설정 값 저장"""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute('''
            INSERT OR REPLACE INTO settings (key, value)
            VALUES (?, ?)
        ''', (key, value))
        conn.commit()
        conn.close()
    
    def delete_setting(self, key):
        """설정 삭제"""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute('DELETE FROM settings WHERE key=?', (key,))
        conn.commit()
        conn.close()

    # ========== 검색 히스토리 관련 메서드 ==========
    def add_search_history(self, site, product_name, price, url):
        """검색 히스토리 추가"""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute('''
            INSERT INTO search_history (site, product_name, price, url)
            VALUES (?, ?, ?, ?)
        ''', (site, product_name, price, url))
        conn.commit()
        conn.close()
    
    def get_search_history(self):
        """최근 24시간 검색 히스토리 조회"""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute('''
            SELECT * FROM search_history
            WHERE datetime(viewed_at) >= datetime('now', '-1 day')
            ORDER BY viewed_at DESC
        ''')
        history = cursor.fetchall()
        conn.close()
        return history
    
    def clear_old_search_history(self):
        """24시간 지난 히스토리 삭제"""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute('''
            DELETE FROM search_history
            WHERE datetime(viewed_at) < datetime('now', '-1 day')
        ''')
        conn.commit()
        conn.close()
    
    def clear_all_search_history(self):
        """모든 검색 히스토리 삭제"""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute('DELETE FROM search_history')
        conn.commit()
        conn.close()
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
# 네이버 쇼핑 API 클래스
# ============================================================
class NaverShoppingAPI:
    """네이버 쇼핑 API를 사용한 검색"""
    
    def __init__(self, client_id, client_secret):
        self.client_id = client_id
        self.client_secret = client_secret
        self.base_url = "https://openapi.naver.com/v1/search/shop.json"
    
    def search_products(self, keyword, max_results=20):
        """
        네이버 쇼핑에서 상품 검색
        
        Args:
            keyword: 검색어
            max_results: 최대 결과 수 (최대 100)
        
        Returns:
            [(순위, 상품명, 가격, 스토어명, URL), ...]
        """
        import urllib.parse
        
        try:
            # URL 인코딩
            encoded_keyword = urllib.parse.quote(keyword)
            
            # API 요청 헤더
            headers = {
                "X-Naver-Client-Id": self.client_id,
                "X-Naver-Client-Secret": self.client_secret
            }
            
            # API 요청 (최대 100개)
            display = min(max_results, 100)
            url = f"{self.base_url}?query={encoded_keyword}&display={display}&sort=sim"
            
            print(f"🔍 API 요청: {keyword}")
            response = requests.get(url, headers=headers, timeout=10)
            
            if response.status_code == 200:
                data = response.json()
                items = data.get('items', [])
                
                products = []
                for idx, item in enumerate(items):
                    try:
                        # 상품명 (HTML 태그 제거)
                        title = item.get('title', '')
                        title = title.replace('<b>', '').replace('</b>', '')
                        
                        # 가격
                        price = int(item.get('lprice', 0))
                        
                        # 스토어명
                        mall_name = item.get('mallName', '알 수 없음')
                        
                        # URL
                        link = item.get('link', '')
                        
                        # 브랜드 정보
                        brand = item.get('brand', '')
                        if brand:
                            title = f"[{brand}] {title}"
                        
                        products.append((idx + 1, title, price, mall_name, link))
                        
                    except Exception as e:
                        print(f"  ⚠️ 상품 {idx + 1} 파싱 실패: {e}")
                        continue
                
                print(f"✅ {len(products)}개 상품 검색 완료")
                return products
            
            elif response.status_code == 401:
                raise Exception("API 인증 실패!\nClient ID 또는 Secret이 잘못되었습니다.")
            elif response.status_code == 429:
                raise Exception("API 호출 한도 초과!\n하루 25,000건 제한을 확인하세요.")
            else:
                raise Exception(f"API 오류 (코드: {response.status_code})")
        
        except requests.exceptions.Timeout:
            raise Exception("API 요청 시간 초과!\n네트워크 연결을 확인하세요.")
        except requests.exceptions.ConnectionError:
            raise Exception("네트워크 연결 실패!")
        except Exception as e:
            raise Exception(f"검색 실패: {str(e)}")
    
    def find_store_rank(self, keyword, store_name):
        """
        특정 스토어의 순위 찾기
        
        Args:
            keyword: 검색어
            store_name: 찾을 스토어명
        
        Returns:
            (순위, 상품명, 가격, URL) 또는 None
        """
        products = self.search_products(keyword, max_results=100)
        
        for rank, name, price, store, url in products:
            if store_name.lower() in store.lower():
                return (rank, name, price, url)
        
        return None
    
    def get_lowest_price(self, keyword):
        """최저가 상품 찾기"""
        products = self.search_products(keyword, max_results=20)
        
        if products:
            return min(products, key=lambda x: x[2])
        return None

# ============================================================
# 다나와 크롤러 클래스
# ============================================================
class DanawaSearchCrawler:
    """다나와 검색 크롤러"""
    
    def search_products(self, keyword, max_results=20):
        """
        다나와에서 상품 검색
        
        Returns:
            [(순위, 상품명, 가격, 스토어명, URL), ...]
        """
        import urllib.parse
        
        try:
            encoded_keyword = urllib.parse.quote(keyword)
            search_url = f"https://search.danawa.com/dsearch.php?query={encoded_keyword}&tab=goods"
            
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
            }
            
            print(f"🔍 다나와 검색: {keyword}")
            response = requests.get(search_url, headers=headers, timeout=10)
            response.raise_for_status()
            
            soup = BeautifulSoup(response.content, 'html.parser')
            
            products = []
            
            # 다나와 상품 리스트 파싱 (여러 선택자 시도)
            product_items = soup.select('li.prod_item')
            
            if not product_items:
                product_items = soup.select('div.product_list > ul > li')
            
            if not product_items:
                product_items = soup.select('div.main_prodlist ul.product_list > li')
            
            print(f"  → {len(product_items)}개 아이템 발견")
            
            for idx, item in enumerate(product_items[:max_results]):
                try:
                    # 상품명
                    name_elem = item.select_one('p.prod_name a')
                    if not name_elem:
                        name_elem = item.select_one('a.prod_name')
                    if not name_elem:
                        name_elem = item.select_one('.prod_name')
                    
                    if not name_elem:
                        continue
                    
                    product_name = name_elem.get_text(strip=True)
                    product_url = name_elem.get('href', '')
                    if product_url and not product_url.startswith('http'):
                        product_url = 'https://prod.danawa.com' + product_url
                    
                    # 가격 (여러 선택자 시도)
                    price = 0
                    price_elem = None
                    
                    # 시도 1: span.price_sect a.lowest_price strong
                    price_elem = item.select_one('span.price_sect a.lowest_price strong')
                    
                    # 시도 2: span.price_sect em
                    if not price_elem:
                        price_elem = item.select_one('span.price_sect em')
                    
                    # 시도 3: a.lowest_price
                    if not price_elem:
                        price_elem = item.select_one('a.lowest_price')
                    
                    # 시도 4: .price strong
                    if not price_elem:
                        price_elem = item.select_one('.price strong')
                    
                    # 시도 5: .price em
                    if not price_elem:
                        price_elem = item.select_one('.price em')
                    
                    # 시도 6: strong (가격 같은 형태)
                    if not price_elem:
                        strong_elems = item.select('strong')
                        for strong in strong_elems:
                            text = strong.get_text(strip=True)
                            if '원' in text or text.replace(',', '').isdigit():
                                price_elem = strong
                                break
                    
                    # 시도 7: em (가격 같은 형태)
                    if not price_elem:
                        em_elems = item.select('em')
                        for em in em_elems:
                            text = em.get_text(strip=True)
                            if '원' in text or (text.replace(',', '').isdigit() and len(text) >= 4):
                                price_elem = em
                                break
                    
                    if price_elem:
                        price_text = price_elem.get_text(strip=True)
                        # 숫자만 추출
                        digits = ''.join(filter(str.isdigit, price_text))
                        if digits:
                            price = int(digits)
                            print(f"  {idx + 1}. {product_name[:30]}... - {price:,}원")
                        else:
                            print(f"  {idx + 1}. {product_name[:30]}... - 가격 파싱 실패 (텍스트: {price_text})")
                    else:
                        # 디버깅: 아이템 HTML 일부 출력
                        print(f"  {idx + 1}. {product_name[:30]}... - 가격 요소 못 찾음")
                        if idx < 3:  # 처음 3개만 디버깅
                            print(f"      HTML 샘플: {str(item)[:200]}...")
                    
                    store_name = "다나와"
                    
                    products.append((idx + 1, product_name, price, store_name, product_url))
                    
                except Exception as e:
                    print(f"  ⚠️ 아이템 {idx + 1} 파싱 실패: {e}")
                    continue
            
            print(f"✅ 다나와 {len(products)}개 검색 완료")
            
            # 가격이 0인 게 많으면 HTML 저장
            zero_price_count = sum(1 for p in products if p[2] == 0)
            if zero_price_count > len(products) / 2:
                with open("danawa_debug.html", "w", encoding="utf-8") as f:
                    f.write(str(soup))
                print(f"⚠️ 가격 파싱 실패가 많습니다. danawa_debug.html 파일을 확인하세요.")
            
            return products
        
        except Exception as e:
            raise Exception(f"다나와 검색 실패: {str(e)}")


# ============================================================
# 11번가 크롤러 클래스
# ============================================================
class Street11Crawler:
    """11번가 검색 크롤러"""
    
    def search_products(self, keyword, max_results=20):
        """
        11번가에서 상품 검색
        
        Returns:
            [(순위, 상품명, 가격, 스토어명, URL), ...]
        """
        import urllib.parse
        
        try:
            encoded_keyword = urllib.parse.quote(keyword)
            search_url = f"https://search.11st.co.kr/Search.tmall?kwd={encoded_keyword}"
            
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
                'Accept-Language': 'ko-KR,ko;q=0.9',
                'Referer': 'https://www.11st.co.kr'
            }
            
            print(f"🔍 11번가 검색: {keyword}")
            response = requests.get(search_url, headers=headers, timeout=10)
            response.raise_for_status()
            
            soup = BeautifulSoup(response.content, 'html.parser')
            
            products = []
            
            # 11번가 상품 리스트 파싱
            product_items = soup.select('div.c_card')
            
            if not product_items:
                product_items = soup.select('li.c_card')
            
            if not product_items:
                product_items = soup.select('div[data-log-actionid-area="product_impression"]')
            
            print(f"  → {len(product_items)}개 아이템 발견")
            
            for idx, item in enumerate(product_items[:max_results]):
                try:
                    # 상품명
                    name_elem = item.select_one('div.c_card__title')
                    if not name_elem:
                        name_elem = item.select_one('a.c_card__link')
                    
                    if not name_elem:
                        continue
                    
                    product_name = name_elem.get_text(strip=True)
                    
                    # URL
                    link_elem = item.select_one('a.c_card__link')
                    if not link_elem:
                        link_elem = item.select_one('a')
                    
                    product_url = link_elem.get('href', '') if link_elem else search_url
                    if product_url and not product_url.startswith('http'):
                        product_url = 'https://www.11st.co.kr' + product_url
                    
                    # 가격
                    price = 0
                    price_elem = None
                    
                    # 시도 1: div.c_card__price strong
                    price_elem = item.select_one('div.c_card__price strong')
                    
                    # 시도 2: span.c_card__price
                    if not price_elem:
                        price_elem = item.select_one('span.c_card__price')
                    
                    # 시도 3: .price strong
                    if not price_elem:
                        price_elem = item.select_one('.price strong')
                    
                    # 시도 4: strong 중에서 가격 형태
                    if not price_elem:
                        strong_elems = item.select('strong')
                        for strong in strong_elems:
                            text = strong.get_text(strip=True)
                            if '원' in text or (text.replace(',', '').isdigit() and len(text.replace(',', '')) >= 3):
                                price_elem = strong
                                break
                    
                    if price_elem:
                        price_text = price_elem.get_text(strip=True)
                        digits = ''.join(filter(str.isdigit, price_text))
                        if digits:
                            price = int(digits)
                            print(f"  {idx + 1}. {product_name[:30]}... - {price:,}원")
                    else:
                        print(f"  {idx + 1}. {product_name[:30]}... - 가격 못 찾음")
                    
                    store_name = "11번가"
                    
                    products.append((idx + 1, product_name, price, store_name, product_url))
                    
                except Exception as e:
                    print(f"  ⚠️ 아이템 {idx + 1} 파싱 실패: {e}")
                    continue
            
            print(f"✅ 11번가 {len(products)}개 검색 완료")
            
            # 디버깅: 가격 파싱 실패가 많으면 HTML 저장
            zero_price_count = sum(1 for p in products if p[2] == 0)
            if zero_price_count > len(products) / 2 and products:
                with open("11st_debug.html", "w", encoding="utf-8") as f:
                    f.write(str(soup))
                print(f"⚠️ 가격 파싱 실패가 많습니다. 11st_debug.html 파일을 확인하세요.")
            
            return products
        
        except Exception as e:
            raise Exception(f"11번가 검색 실패: {str(e)}")

# ============================================================
# 쿠팡 파트너스 API 클래스
# ============================================================
class CoupangPartnersAPI:
    """쿠팡 파트너스 API를 사용한 검색"""
    
    def __init__(self, access_key, secret_key):
        self.access_key = access_key
        self.secret_key = secret_key
        self.base_url = "https://api-gateway.coupang.com/v2/providers/affiliate_open_api/apis/openapi/products/search"
    
    def generate_signature(self, method, path, datetime_str):
        """HMAC 서명 생성"""
        import hmac
        import hashlib
        
        message = f"{datetime_str}\n{method}\n{path}\n"
        signature = hmac.new(
            self.secret_key.encode('utf-8'),
            message.encode('utf-8'),
            hashlib.sha256
        ).hexdigest()
        return signature
    
    def search_products(self, keyword, max_results=20):
        """
        쿠팡 파트너스에서 상품 검색
        
        Returns:
            [(순위, 상품명, 가격, 스토어명, URL), ...]
        """
        from datetime import datetime
        import urllib.parse
        
        try:
            # 요청 시간
            request_time = datetime.utcnow().strftime('%y%m%d') + 'T' + datetime.utcnow().strftime('%H%M%S') + 'Z'
            
            # 쿼리 파라미터
            params = {
                'keyword': keyword,
                'limit': min(max_results, 100)
            }
            
            query_string = urllib.parse.urlencode(params)
            path = f"/v2/providers/affiliate_open_api/apis/openapi/products/search?{query_string}"
            
            # 서명 생성
            signature = self.generate_signature('GET', path, request_time)
            
            # 헤더
            headers = {
                'Authorization': f"CEA algorithm=HmacSHA256, access-key={self.access_key}, signed-date={request_time}, signature={signature}",
                'Content-Type': 'application/json'
            }
            
            # API 요청
            url = self.base_url + '?' + query_string
            print(f"🔍 쿠팡 파트너스 검색: {keyword}")
            response = requests.get(url, headers=headers, timeout=10)
            
            if response.status_code == 200:
                data = response.json()
                products = []
                
                items = data.get('data', [])
                for idx, item in enumerate(items):
                    try:
                        product_name = item.get('productName', '')
                        price = int(item.get('productPrice', 0))
                        product_url = item.get('productUrl', '')
                        
                        products.append((idx + 1, product_name, price, "쿠팡", product_url))
                    except:
                        continue
                
                print(f"✅ 쿠팡 {len(products)}개 검색 완료")
                return products
            
            elif response.status_code == 401:
                raise Exception("쿠팡 API 인증 실패!\nAccess Key 또는 Secret Key를 확인하세요.")
            elif response.status_code == 403:
                raise Exception("쿠팡 API 권한 없음!\n파트너스 승인이 완료되었는지 확인하세요.")
            else:
                raise Exception(f"쿠팡 API 오류 (코드: {response.status_code})")
        
        except Exception as e:
            raise Exception(f"쿠팡 검색 실패: {str(e)}")


# ============================================================
# 알리익스프레스 크롤러 클래스
# ============================================================
class AliexpressSearchCrawler:
    """알리익스프레스 검색 크롤러"""
    
    def search_products(self, keyword, max_results=20):
        """알리익스프레스에서 상품 검색"""
        import urllib.parse
        
        try:
            encoded_keyword = urllib.parse.quote(keyword)
            search_url = f"https://ko.aliexpress.com/wholesale?SearchText={encoded_keyword}"
            
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                'Accept-Language': 'ko-KR,ko;q=0.9'
            }
            
            print(f"🔍 알리익스프레스 검색: {keyword}")
            response = requests.get(search_url, headers=headers, timeout=10)
            response.raise_for_status()
            
            soup = BeautifulSoup(response.content, 'html.parser')
            products = []
            
            # 상품 리스트
            product_items = soup.select('div.list--gallery--C2f2tvm')
            
            if not product_items:
                product_items = soup.select('div[class*="list--gallery"]')
            
            print(f"  → {len(product_items)}개 아이템 발견")
            
            for idx, item in enumerate(product_items[:max_results]):
                try:
                    # 상품명
                    name_elem = item.select_one('h3')
                    if not name_elem:
                        name_elem = item.select_one('a[title]')
                    
                    if name_elem:
                        product_name = name_elem.get_text(strip=True) or name_elem.get('title', '')
                    else:
                        continue
                    
                    # URL
                    link_elem = item.select_one('a')
                    product_url = link_elem.get('href', '') if link_elem else search_url
                    if product_url and not product_url.startswith('http'):
                        product_url = 'https:' + product_url
                    
                    # 가격 (USD 또는 KRW)
                    price = 0
                    price_elem = item.select_one('div[class*="price"]')
                    
                    if price_elem:
                        price_text = price_elem.get_text(strip=True)
                        digits = ''.join(filter(str.isdigit, price_text))
                        if digits:
                            price = int(digits)
                    
                    products.append((idx + 1, product_name, price, "알리익스프레스", product_url))
                    
                except Exception as e:
                    continue
            
            print(f"✅ 알리익스프레스 {len(products)}개 검색 완료")
            return products
        
        except Exception as e:
            raise Exception(f"알리익스프레스 검색 실패: {str(e)}")


# ============================================================
# 옥션 크롤러 클래스
# ============================================================
class AuctionSearchCrawler:
    """옥션 검색 크롤러"""
    
    def search_products(self, keyword, max_results=20):
        """옥션에서 상품 검색"""
        import urllib.parse
        
        try:
            encoded_keyword = urllib.parse.quote(keyword)
            search_url = f"http://browse.auction.co.kr/search?keyword={encoded_keyword}"
            
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
            }
            
            print(f"🔍 옥션 검색: {keyword}")
            response = requests.get(search_url, headers=headers, timeout=10)
            response.raise_for_status()
            
            soup = BeautifulSoup(response.content, 'html.parser')
            products = []
            
            # 상품 리스트
            product_items = soup.select('div.component--item_card')
            
            if not product_items:
                product_items = soup.select('li[class*="item"]')
            
            print(f"  → {len(product_items)}개 아이템 발견")
            
            for idx, item in enumerate(product_items[:max_results]):
                try:
                    # 상품명
                    name_elem = item.select_one('span.text--title')
                    if not name_elem:
                        name_elem = item.select_one('a.link--text')
                    
                    if not name_elem:
                        continue
                    
                    product_name = name_elem.get_text(strip=True)
                    
                    # URL
                    link_elem = item.select_one('a')
                    product_url = link_elem.get('href', '') if link_elem else search_url
                    if product_url and not product_url.startswith('http'):
                        product_url = 'http://www.auction.co.kr' + product_url
                    
                    # 가격
                    price = 0
                    price_elem = item.select_one('strong.text--price_value')
                    
                    if not price_elem:
                        price_elem = item.select_one('span[class*="price"]')
                    
                    if price_elem:
                        price_text = price_elem.get_text(strip=True)
                        digits = ''.join(filter(str.isdigit, price_text))
                        if digits:
                            price = int(digits)
                    
                    products.append((idx + 1, product_name, price, "옥션", product_url))
                    
                except Exception as e:
                    continue
            
            print(f"✅ 옥션 {len(products)}개 검색 완료")
            return products
        
        except Exception as e:
            raise Exception(f"옥션 검색 실패: {str(e)}")


# ============================================================
# G마켓 크롤러 클래스
# ============================================================
class GmarketSearchCrawler:
    """G마켓 검색 크롤러"""
    
    def search_products(self, keyword, max_results=20):
        """G마켓에서 상품 검색"""
        import urllib.parse
        
        try:
            encoded_keyword = urllib.parse.quote(keyword)
            search_url = f"http://browse.gmarket.co.kr/search?keyword={encoded_keyword}"
            
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
            }
            
            print(f"🔍 G마켓 검색: {keyword}")
            response = requests.get(search_url, headers=headers, timeout=10)
            response.raise_for_status()
            
            soup = BeautifulSoup(response.content, 'html.parser')
            products = []
            
            # 상품 리스트
            product_items = soup.select('div.box__component-itemcard')
            
            if not product_items:
                product_items = soup.select('div[class*="item"]')
            
            print(f"  → {len(product_items)}개 아이템 발견")
            
            for idx, item in enumerate(product_items[:max_results]):
                try:
                    # 상품명
                    name_elem = item.select_one('span.text__item')
                    if not name_elem:
                        name_elem = item.select_one('a[title]')
                    
                    if not name_elem:
                        continue
                    
                    product_name = name_elem.get_text(strip=True) or name_elem.get('title', '')
                    
                    # URL
                    link_elem = item.select_one('a')
                    product_url = link_elem.get('href', '') if link_elem else search_url
                    if product_url and not product_url.startswith('http'):
                        product_url = 'http://item.gmarket.co.kr' + product_url
                    
                    # 가격
                    price = 0
                    price_elem = item.select_one('strong.text__value')
                    
                    if not price_elem:
                        price_elem = item.select_one('span[class*="price"]')
                    
                    if price_elem:
                        price_text = price_elem.get_text(strip=True)
                        digits = ''.join(filter(str.isdigit, price_text))
                        if digits:
                            price = int(digits)
                    
                    products.append((idx + 1, product_name, price, "G마켓", product_url))
                    
                except Exception as e:
                    continue
            
            print(f"✅ G마켓 {len(products)}개 검색 완료")
            return products
        
        except Exception as e:
            raise Exception(f"G마켓 검색 실패: {str(e)}")

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
# API 설정 다이얼로그
# ============================================================
class APISettingsDialog(QDialog):
    """네이버 쇼핑 API 키 설정"""
    
    def __init__(self, db_manager, parent=None):
        super().__init__(parent)
        self.db = db_manager
        self.init_ui()
    
    def init_ui(self):
        self.setWindowTitle("🔑 네이버 쇼핑 API 설정")
        self.setMinimumWidth(550)
        
        layout = QVBoxLayout(self)
        
        # 타이틀
        title = QLabel("🔑 네이버 쇼핑 API 키 설정")
        title.setFont(QFont("Malgun Gothic", 14, QFont.Weight.Bold))
        layout.addWidget(title)
        
        # 안내 문구
        info_text = QLabel(
            "네이버 개발자 센터에서 발급받은 API 키를 입력하세요.\n"
            "API 키가 없으면 네이버 쇼핑 검색 기능을 사용할 수 없습니다."
        )
        info_text.setStyleSheet("color: #6b7280; font-size: 11px; margin: 10px 0;")
        info_text.setWordWrap(True)
        layout.addWidget(info_text)
        
        # 입력 폼
        form_layout = QFormLayout()
        
        # 네이버
        naver_label = QLabel("━━━ 네이버 쇼핑 ━━━")
        naver_label.setStyleSheet("font-weight: bold; color: #10b981;")
        form_layout.addRow(naver_label)
        
        self.input_client_id = QLineEdit()
        self.input_client_id.setPlaceholderText("예: Access Key")
        form_layout.addRow("Client ID:", self.input_client_id)
        
        self.input_client_secret = QLineEdit()
        self.input_client_secret.setPlaceholderText("예: Secret Key")
        self.input_client_secret.setEchoMode(QLineEdit.EchoMode.Password)
        form_layout.addRow("Client Secret:", self.input_client_secret)
        
        # 쿠팡 (새로 추가!)
        coupang_label = QLabel("━━━ 쿠팡 파트너스 ━━━")
        coupang_label.setStyleSheet("font-weight: bold; color: #3b82f6; margin-top: 15px;")
        form_layout.addRow(coupang_label)
        
        self.input_coupang_access = QLineEdit()
        self.input_coupang_access.setPlaceholderText("Access Key")
        form_layout.addRow("Access Key:", self.input_coupang_access)
        
        self.input_coupang_secret = QLineEdit()
        self.input_coupang_secret.setPlaceholderText("Secret Key")
        self.input_coupang_secret.setEchoMode(QLineEdit.EchoMode.Password)
        form_layout.addRow("Secret Key:", self.input_coupang_secret)
        
        layout.addLayout(form_layout)
        
        # 비밀번호 표시/숨김 체크박스
        self.check_show_secret = QPushButton("👁️ Secret 보기")
        self.check_show_secret.setCheckable(True)
        self.check_show_secret.setStyleSheet("""
            QPushButton {
                background-color: transparent;
                border: none;
                color: #3b82f6;
                text-align: left;
                padding: 4px;
                font-size: 11px;
            }
            QPushButton:hover {
                color: #2563eb;
                text-decoration: underline;
            }
        """)
        self.check_show_secret.toggled.connect(self.toggle_secret_visibility)
        layout.addWidget(self.check_show_secret)
        
        # 가이드 박스
        guide_box = QWidget()
        guide_box.setStyleSheet("""
            QWidget {
                background-color: #eff6ff;
                border: 1px solid #3b82f6;
                border-radius: 4px;
                padding: 12px;
            }
        """)
        guide_layout = QVBoxLayout(guide_box)
        
        guide_title = QLabel("📘 API 키 발급 방법")
        guide_title.setFont(QFont("Malgun Gothic", 11, QFont.Weight.Bold))
        guide_layout.addWidget(guide_title)
        
        guide_steps = QLabel(
            "1. https://developers.naver.com/apps/#/register 접속\n"
            "2. 네이버 로그인\n"
            "3. '애플리케이션 등록' 클릭\n"
            "4. 애플리케이션 이름 입력 (예: 가격비교)\n"
            "5. 사용 API: '검색 (쇼핑)' 체크\n"
            "6. 등록하기 클릭\n"
            "7. Client ID와 Client Secret 복사"
        )
        guide_steps.setStyleSheet("font-size: 11px; color: #1e40af; line-height: 150%;")
        guide_layout.addWidget(guide_steps)
        
        # 링크 버튼
        btn_open_link = QPushButton("🌐 네이버 개발자 센터 열기")
        btn_open_link.setStyleSheet("""
            QPushButton {
                background-color: #10b981;
                color: white;
                font-weight: bold;
                padding: 6px 12px;
                border-radius: 4px;
                font-size: 11px;
            }
            QPushButton:hover {
                background-color: #059669;
            }
        """)
        btn_open_link.clicked.connect(self.open_developer_site)
        guide_layout.addWidget(btn_open_link)
        
        layout.addWidget(guide_box)
        
        # 버튼
        button_box = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        button_box.accepted.connect(self.save_settings)
        button_box.rejected.connect(self.reject)
        layout.addWidget(button_box)
        
        # 기존 설정 로드
        self.load_current_settings()
    
    def load_current_settings(self):
        """기존 설정 불러오기"""
        # 네이버
        client_id = self.db.get_setting('naver_api_client_id')
        client_secret = self.db.get_setting('naver_api_client_secret')
        
        if client_id:
            self.input_client_id.setText(client_id)
        if client_secret:
            self.input_client_secret.setText(client_secret)
        
        # 쿠팡 (새로 추가!)
        coupang_access = self.db.get_setting('coupang_access_key')
        coupang_secret = self.db.get_setting('coupang_secret_key')
        
        if coupang_access:
            self.input_coupang_access.setText(coupang_access)
        if coupang_secret:
            self.input_coupang_secret.setText(coupang_secret)
    
    def toggle_secret_visibility(self, checked):
        """Secret 표시/숨김"""
        if checked:
            self.input_client_secret.setEchoMode(QLineEdit.EchoMode.Normal)
            self.check_show_secret.setText("🙈 Secret 숨기기")
        else:
            self.input_client_secret.setEchoMode(QLineEdit.EchoMode.Password)
            self.check_show_secret.setText("👁️ Secret 보기")
    
    def open_developer_site(self):
        """네이버 개발자 센터 열기"""
        import webbrowser
        webbrowser.open("https://developers.naver.com/apps/#/register")
    
    def save_settings(self):
        """설정 저장"""
        # 네이버
        client_id = self.input_client_id.text().strip()
        client_secret = self.input_client_secret.text().strip()
        
        # 쿠팡
        coupang_access = self.input_coupang_access.text().strip()
        coupang_secret = self.input_coupang_secret.text().strip()
        
        # 최소 하나는 입력되어야 함
        if not any([client_id, client_secret, coupang_access, coupang_secret]):
            QMessageBox.warning(self, "입력 오류", "최소 하나의 API 키를 입력하세요!")
            return
        
        # DB에 저장
        if client_id:
            self.db.set_setting('naver_api_client_id', client_id)
        if client_secret:
            self.db.set_setting('naver_api_client_secret', client_secret)
        
        if coupang_access:
            self.db.set_setting('coupang_access_key', coupang_access)
        if coupang_secret:
            self.db.set_setting('coupang_secret_key', coupang_secret)
        
        QMessageBox.information(self, "완료", "API 키가 저장되었습니다!")
        self.accept()

# ============================================================
# 네이버 쇼핑 검색 다이얼로그
# ============================================================
class NaverShoppingDialog(QDialog):
    """네이버 쇼핑 검색 및 순위 조회"""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.parent_window = parent
        self.api = None
        self.results = []
        self.init_ui()
        self.load_api_keys()
    
    def load_api_keys(self):
        """DB에서 API 키 불러오기"""
        if not self.parent_window:
            return
        
        db = self.parent_window.db
        client_id = db.get_setting('naver_api_client_id')
        client_secret = db.get_setting('naver_api_client_secret')
        
        if client_id and client_secret:
            self.api = NaverShoppingAPI(client_id, client_secret)
            self.status_label.setText("✅ API 키가 로드되었습니다. 검색어를 입력하세요.")
        else:
            self.api = None
            self.status_label.setText("⚠️ API 키가 설정되지 않았습니다. '관리' 탭에서 설정하세요.")
            self.btn_search.setEnabled(False)
            self.btn_find_rank.setEnabled(False)
            
            # 안내 메시지
            QMessageBox.warning(
                self, "API 키 필요",
                "네이버 쇼핑 API 키가 설정되지 않았습니다.\n\n"
                "사용 방법:\n"
                "1. '⚙️ 관리' 탭으로 이동\n"
                "2. '🔑 API 설정' 버튼 클릭\n"
                "3. API 키 입력 후 저장\n"
                "4. 다시 시도하세요."
            )
    
    def init_ui(self):
        self.setWindowTitle("🛒 네이버 쇼핑 검색")
        self.resize(900, 700)
        
        layout = QVBoxLayout(self)
        
        # 타이틀
        title = QLabel("🛒 네이버 쇼핑 가격 비교")
        title.setFont(QFont("Malgun Gothic", 14, QFont.Weight.Bold))
        layout.addWidget(title)
        
        # 검색 영역
        search_group = QWidget()
        search_layout = QFormLayout(search_group)
        
        self.input_keyword = QLineEdit()
        self.input_keyword.setPlaceholderText("예: 남성 후드티")
        search_layout.addRow("검색어*:", self.input_keyword)
        
        self.input_store = QLineEdit()
        self.input_store.setPlaceholderText("예: 넥스트세이프 (선택사항)")
        search_layout.addRow("스토어명:", self.input_store)
        
        layout.addWidget(search_group)
        
        # 버튼 그룹
        btn_layout = QHBoxLayout()
        
        self.btn_search = QPushButton("🔍 검색")
        self.btn_search.setStyleSheet("""
            QPushButton {
                background-color: #10b981;
                color: white;
                font-weight: bold;
                padding: 10px 20px;
                border-radius: 4px;
                font-size: 13px;
            }
            QPushButton:hover {
                background-color: #059669;
            }
        """)
        self.btn_search.clicked.connect(self.search_naver)
        
        self.btn_find_rank = QPushButton("📊 순위 찾기")
        self.btn_find_rank.setStyleSheet("""
            QPushButton {
                background-color: #3b82f6;
                color: white;
                font-weight: bold;
                padding: 10px 20px;
                border-radius: 4px;
                font-size: 13px;
            }
            QPushButton:hover {
                background-color: #2563eb;
            }
        """)
        self.btn_find_rank.clicked.connect(self.find_store_rank)
        
        btn_layout.addWidget(self.btn_search)
        btn_layout.addWidget(self.btn_find_rank)
        btn_layout.addStretch()
        layout.addLayout(btn_layout)
        
        # 결과 테이블
        result_label = QLabel("📋 검색 결과 (더블클릭하면 페이지 열림)")
        result_label.setFont(QFont("Malgun Gothic", 11, QFont.Weight.Bold))
        layout.addWidget(result_label)
        
        self.result_table = QTableWidget()
        self.result_table.setColumnCount(5)
        self.result_table.setHorizontalHeaderLabels(["순위", "상품명", "가격", "스토어", "URL"])
        
        # 컬럼 너비 개별 설정
        header = self.result_table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)  # 순위
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)  # 상품명 (자동 확장)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Fixed)  # 가격
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.Fixed)  # 스토어
        header.setSectionResizeMode(4, QHeaderView.ResizeMode.Fixed)  # URL
        
        # 컬럼 너비 지정
        self.result_table.setColumnWidth(0, 50)   # 순위: 50px (작게)
        self.result_table.setColumnWidth(2, 100)  # 가격: 100px (작게)
        self.result_table.setColumnWidth(3, 120)  # 스토어: 120px
        self.result_table.setColumnWidth(4, 150)  # URL: 150px
        # 상품명(1)은 Stretch로 남은 공간 모두 차지
        
        self.result_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.result_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.result_table.itemDoubleClicked.connect(self.open_product_url)
        
        # 테이블 스타일 개선
        self.result_table.setAlternatingRowColors(True)
        self.result_table.setStyleSheet("""
            QTableWidget {
                gridline-color: #e5e7eb;
                alternate-background-color: #f9fafb;
            }
            QTableWidget::item {
                padding: 8px;
            }
            QHeaderView::section {
                background-color: #f3f4f6;
                padding: 8px;
                border: none;
                font-weight: bold;
                font-size: 11px;
            }
        """)
        
        layout.addWidget(self.result_table)
        
        # 상태 라벨
        self.status_label = QLabel("검색어를 입력하고 '검색' 버튼을 누르세요.")
        self.status_label.setStyleSheet("color: #6b7280; font-size: 11px;")
        layout.addWidget(self.status_label)
        
        # 닫기 버튼
        close_btn = QPushButton("닫기")
        close_btn.clicked.connect(self.close_dialog)
        layout.addWidget(close_btn)
    
    def search_naver(self):
        """네이버 쇼핑 API 검색"""
        if not self.api:
            QMessageBox.warning(self, "API 키 없음", "API 키를 먼저 설정하세요!\n'⚙️ 관리' 탭 → '🔑 API 설정'")
            return
        
        keyword = self.input_keyword.text().strip()
        if not keyword:
            QMessageBox.warning(self, "입력 오류", "검색어를 입력하세요!")
            return
        
        self.status_label.setText("🔄 검색 중... (API 호출)")
        self.btn_search.setEnabled(False)
        self.btn_find_rank.setEnabled(False)
        QApplication.processEvents()
        
        try:
            # API 검색 실행
            self.results = self.api.search_products(keyword, max_results=20)
            
            # 테이블에 표시
            self.result_table.setRowCount(len(self.results))
            
            for i, (rank, name, price, store, url) in enumerate(self.results):
                self.result_table.setItem(i, 0, QTableWidgetItem(str(rank)))
                self.result_table.setItem(i, 1, QTableWidgetItem(name))
                
                price_item = QTableWidgetItem(f"{price:,}원")
                price_item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                self.result_table.setItem(i, 2, price_item)
                
                self.result_table.setItem(i, 3, QTableWidgetItem(store))
                
                url_item = QTableWidgetItem(url[:50] + "...")
                url_item.setData(Qt.ItemDataRole.UserRole, url)
                self.result_table.setItem(i, 4, url_item)
            
            # 최저가 찾기
            if self.results:
                min_price = min(self.results, key=lambda x: x[2])
                self.status_label.setText(f"✅ {len(self.results)}개 검색 완료 | 최저가: {min_price[2]:,}원 ({min_price[3]})")
            else:
                self.status_label.setText("❌ 검색 결과가 없습니다.")
        
        except Exception as e:
            error_msg = str(e)
            QMessageBox.critical(
                self, "검색 실패",
                f"오류 발생:\n{error_msg}"
            )
            self.status_label.setText(f"❌ 오류: {error_msg}")
        
        finally:
            self.btn_search.setEnabled(True)
            self.btn_find_rank.setEnabled(True)
    
    def find_store_rank(self):
        """특정 스토어 순위 찾기 (API)"""
        if not self.api:
            QMessageBox.warning(self, "API 키 없음", "API 키를 먼저 설정하세요!\n'⚙️ 관리' 탭 → '🔑 API 설정'")
            return
        
        keyword = self.input_keyword.text().strip()
        store_name = self.input_store.text().strip()
        
        self.status_label.setText(f"🔄 '{store_name}' 순위 검색 중...")
        self.btn_search.setEnabled(False)
        self.btn_find_rank.setEnabled(False)
        QApplication.processEvents()
        
        try:
            result = self.api.find_store_rank(keyword, store_name)
            
            if result:
                rank, name, price, url = result
                QMessageBox.information(
                    self, "순위 찾기 성공",
                    f"🎯 찾았습니다!\n\n"
                    f"순위: {rank}위\n"
                    f"상품명: {name}\n"
                    f"가격: {price:,}원\n"
                    f"검색어: {keyword}"
                )
                self.status_label.setText(f"✅ '{store_name}' 찾음: {rank}위")
            else:
                QMessageBox.information(
                    self, "결과 없음",
                    f"'{store_name}' 스토어를 상위 100위 안에서 찾지 못했습니다.\n\n"
                    f"팁:\n"
                    f"- 스토어명 철자 확인\n"
                    f"- 검색어 변경\n"
                    f"- 더 일반적인 검색어 사용"
                )
                self.status_label.setText(f"❌ '{store_name}' 찾지 못함")
        
        except Exception as e:
            QMessageBox.critical(self, "검색 실패", f"오류 발생:\n{str(e)}")
            self.status_label.setText(f"❌ 오류: {str(e)}")
        
        finally:
            self.btn_search.setEnabled(True)
            self.btn_find_rank.setEnabled(True)
    
    def open_product_url(self, item):
        """상품 URL 열기"""
        row = item.row()
        url_item = self.result_table.item(row, 4)
        url = url_item.data(Qt.ItemDataRole.UserRole)
        
        if url:
            import webbrowser
            webbrowser.open(url)
    
    def close_dialog(self):
        """다이얼로그 닫기"""
        self.close()

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
        
        # 가격
        self.input_price = QSpinBox()
        self.input_price.setMaximum(999999999)
        self.input_price.setSuffix(" 원")
        form_layout.addRow("가격*:", self.input_price)
        
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
        """기존 상품 데이터 로드"""
        p = self.product_data
        self.combo_large.setCurrentText(p[1] or "")
        self.combo_medium.setCurrentText(p[2] or "")
        self.combo_small.setCurrentText(p[3] or "")
        self.input_name.setText(p[4])
        self.input_vendor.setText(p[5])
        self.input_price.setValue(p[6])
        self.input_url.setText(p[7] or "")
        self.input_selector.setText(p[8] or "")
        self.input_memo.setText(p[9] or "")
    
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
        return {
            'category_large': self.combo_large.currentText(),
            'category_medium': self.combo_medium.currentText(),
            'category_small': self.combo_small.currentText(),
            'product_name': self.input_name.text(),
            'vendor': self.input_vendor.text(),
            'price': self.input_price.value(),
            'url': self.input_url.text(),
            'css_selector': self.input_selector.text(),
            'memo': self.input_memo.toPlainText()
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
        self.setWindowTitle("시장조사 툴 v2.0")
        self.resize(1400, 900)
        
        # DB 초기화
        self.db = DatabaseManager()
        
        # 상태 관리
        self.current_product_id = None
        
        # 자동 새로고침 설정
        self.auto_refresh_enabled = False
        self.refresh_interval = 30000  # 30초 (밀리초 단위)
        
        self.init_ui()
        self.load_initial_data()
        
        # F5 단축키 설정
        self.setup_shortcuts()
        
        # 자동 새로고침 타이머 설정
        self.setup_auto_refresh()
    
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
        
        # 검색 탭 (새로 추가!)
        self.search_tab = QWidget()
        self.setup_search_tab()
        self.tabs.addTab(self.search_tab, "🔍 검색")
        
        # 관리 탭
        self.manage_tab = QWidget()
        self.setup_manage_tab()
        self.tabs.addTab(self.manage_tab, "⚙️ 관리")
        
        # 탭 위젯을 메인 레이아웃에 추가
        main_layout.addWidget(self.tabs)
        
        # 상태바 추가
        self.statusBar().showMessage("✨ 프로그램 시작 | F5: 새로고침")
        
        # 하단 정보 바 추가
        self.setup_bottom_bar()
    
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
        self.panel_center.setVisible(True)
        self.setup_center_panel()
        splitter.addWidget(self.panel_center)
        
        # [3구역] 우측: 그래프 및 즐겨찾기
        self.panel_right = QWidget()
        self.setup_right_panel()
        splitter.addWidget(self.panel_right)
        
        splitter.setSizes([300, 540, 360])
        layout.addWidget(splitter)
    
    def setup_search_tab(self):
        """검색 탭 구성"""
        layout = QHBoxLayout(self.search_tab)
        layout.setContentsMargins(0, 0, 0, 0)
        
        splitter = QSplitter(Qt.Orientation.Horizontal)
        
        # 좌측: 검색 영역
        left_panel = QWidget()
        left_layout = QVBoxLayout(left_panel)
        left_layout.setContentsMargins(10, 10, 10, 10)
        
        # 타이틀
        title = QLabel("🔍 상품 검색")
        title.setFont(QFont("Malgun Gothic", 12, QFont.Weight.Bold))
        left_layout.addWidget(title)
        
        # 검색 옵션
        search_form = QWidget()
        search_form_layout = QFormLayout(search_form)
        
        # 사이트 선택
        self.search_site_combo = QComboBox()
        self.search_site_combo.addItems([
            "네이버 쇼핑",
            "다나와",
            "쿠팡"  # (승인 후 사용 가능)
        ])
        search_form_layout.addRow("사이트:", self.search_site_combo)
        
        # 검색어
        self.search_keyword_input = QLineEdit()
        self.search_keyword_input.setPlaceholderText("예: 남성 후드티")
        self.search_keyword_input.returnPressed.connect(self.execute_search)
        search_form_layout.addRow("검색어:", self.search_keyword_input)
        
        left_layout.addWidget(search_form)
        
        # 검색 버튼
        self.btn_execute_search = QPushButton("🔍 검색")
        self.btn_execute_search.setStyleSheet("""
            QPushButton {
                background-color: #10b981;
                color: white;
                font-weight: bold;
                padding: 10px;
                border-radius: 4px;
                font-size: 13px;
            }
            QPushButton:hover {
                background-color: #059669;
            }
        """)
        self.btn_execute_search.clicked.connect(self.execute_search)
        left_layout.addWidget(self.btn_execute_search)
        
        # 검색 결과 라벨
        result_label = QLabel("📋 검색 결과 (더블클릭하면 히스토리에 추가)")
        result_label.setFont(QFont("Malgun Gothic", 11, QFont.Weight.Bold))
        result_label.setStyleSheet("margin-top: 10px;")
        left_layout.addWidget(result_label)
        
        # 검색 결과 테이블
        self.search_result_table = QTableWidget()
        self.search_result_table.setColumnCount(4)
        self.search_result_table.setHorizontalHeaderLabels(["순위", "상품명", "가격", "URL"])
        
        header = self.search_result_table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Fixed)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.Fixed)
        
        self.search_result_table.setColumnWidth(0, 50)
        self.search_result_table.setColumnWidth(2, 100)
        self.search_result_table.setColumnWidth(3, 150)
        
        self.search_result_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.search_result_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.search_result_table.itemDoubleClicked.connect(self.add_to_history)
        
        # 헤더 클릭 정렬 활성화
        header.setSortIndicatorShown(True)
        header.sectionClicked.connect(self.sort_search_results)
        
        # 초기 정렬 상태 저장
        self.current_search_results = []
        self.current_sort_column = None
        self.current_sort_order = Qt.SortOrder.AscendingOrder
        
        left_layout.addWidget(self.search_result_table)
        
        # 상태 라벨
        self.search_status_label = QLabel("검색어를 입력하고 검색 버튼을 누르세요.")
        self.search_status_label.setStyleSheet("color: #6b7280; font-size: 11px;")
        left_layout.addWidget(self.search_status_label)
        
        splitter.addWidget(left_panel)
        
        # 우측: 최근 본 상품 히스토리
        right_panel = QWidget()
        right_layout = QVBoxLayout(right_panel)
        right_layout.setContentsMargins(10, 10, 10, 10)
        
        # 헤더
        history_header = QHBoxLayout()
        history_title = QLabel("📜 최근 본 상품 (24시간)")
        history_title.setFont(QFont("Malgun Gothic", 12, QFont.Weight.Bold))
        
        btn_export_excel = QPushButton("📥 엑셀 저장")
        btn_export_excel.setStyleSheet("""
            QPushButton {
                background-color: #059669;
                color: white;
                font-weight: bold;
                padding: 6px 12px;
                border-radius: 4px;
            }
            QPushButton:hover {
                background-color: #047857;
            }
        """)
        btn_export_excel.clicked.connect(self.export_history_to_excel)
        
        btn_clear_history = QPushButton("🗑️ 전체 삭제")
        btn_clear_history.setStyleSheet("""
            QPushButton {
                background-color: #dc2626;
                color: white;
                font-weight: bold;
                padding: 6px 12px;
                border-radius: 4px;
            }
            QPushButton:hover {
                background-color: #b91c1c;
            }
        """)
        btn_clear_history.clicked.connect(self.clear_search_history)
        
        history_header.addWidget(history_title)
        history_header.addStretch()
        history_header.addWidget(btn_export_excel)
        history_header.addWidget(btn_clear_history)
        right_layout.addLayout(history_header)
        
        # 새로고침 버튼 추가
        btn_refresh_search = QPushButton("🔄")
        btn_refresh_search.setToolTip("새로고침 (F5)")
        btn_refresh_search.setMaximumWidth(40)
        btn_refresh_search.setStyleSheet("""
            QPushButton {
                background-color: #6b7280;
                color: white;
                font-weight: bold;
                padding: 6px 8px;
                border-radius: 4px;
            }
            QPushButton:hover {
                background-color: #4b5563;
            }
        """)
        btn_refresh_search.clicked.connect(self.refresh_search_tab)
        
        history_header.addWidget(history_title)
        history_header.addStretch()
        history_header.addWidget(btn_refresh_search)  # 추가!
        history_header.addWidget(btn_export_excel)
        history_header.addWidget(btn_clear_history)

        # 히스토리 테이블
        self.history_table = QTableWidget()
        self.history_table.setColumnCount(5)
        self.history_table.setHorizontalHeaderLabels(["시간", "사이트", "상품명", "가격", "URL"])
        
        history_header_obj = self.history_table.horizontalHeader()
        history_header_obj.setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)
        history_header_obj.setSectionResizeMode(1, QHeaderView.ResizeMode.Fixed)
        history_header_obj.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        history_header_obj.setSectionResizeMode(3, QHeaderView.ResizeMode.Fixed)
        history_header_obj.setSectionResizeMode(4, QHeaderView.ResizeMode.Fixed)
        
        self.history_table.setColumnWidth(0, 120)
        self.history_table.setColumnWidth(1, 80)
        self.history_table.setColumnWidth(3, 100)
        self.history_table.setColumnWidth(4, 100)
        
        self.history_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.history_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.history_table.itemDoubleClicked.connect(self.open_history_url)
        
        right_layout.addWidget(self.history_table)
        
        splitter.addWidget(right_panel)
        splitter.setSizes([600, 400])
        
        layout.addWidget(splitter)
        
        # 초기 히스토리 로드
        self.refresh_search_history()

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
        
        # 새로고침 버튼
        btn_refresh_home = QPushButton("🔄")
        btn_refresh_home.setToolTip("새로고침 (F5)")
        btn_refresh_home.setMaximumWidth(40)
        btn_refresh_home.setStyleSheet("""
            QPushButton {
                background-color: #6b7280;
                color: white;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #4b5563;
            }
        """)
        btn_refresh_home.clicked.connect(self.refresh_home_tab)
        
        btn_layout.addWidget(self.btn_add_product)
        btn_layout.addWidget(btn_refresh_home)
        layout.addLayout(btn_layout)
        
        # 검색창
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("🔍 상품명 또는 판매처 검색...")
        self.search_input.textChanged.connect(self.refresh_product_list)
        layout.addWidget(self.search_input)
        
        # 상품 리스트
        self.product_list_widget = QListWidget()
        self.product_list_widget.itemClicked.connect(self.on_product_clicked)
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
        
        # 테이블 - 기존 방식!
        self.history_table = QTableWidget()
        self.history_table.setColumnCount(5)
        self.history_table.setHorizontalHeaderLabels(["날짜", "시간", "매입처", "가격", "변동폭"])
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
        
        # API 설정 버튼 추가
        btn_api_settings = QPushButton("🔑 API 설정")
        btn_api_settings.setStyleSheet("""
            QPushButton {
                background-color: #3b82f6;
                color: white;
                font-weight: bold;
                padding: 8px 16px;
                border-radius: 4px;
            }
            QPushButton:hover {
                background-color: #2563eb;
            }
        """)
        btn_api_settings.clicked.connect(self.open_api_settings)
        btn_layout.addWidget(btn_api_settings)
        
        layout.addLayout(btn_layout)
    
    # ========================================
    # 데이터 로드 및 갱신
    # ========================================
    def load_initial_data(self):
        """초기 데이터 로드"""
        self.refresh_product_list()
        self.refresh_bookmarks()
        self.refresh_manage_table()

    def setup_shortcuts(self):
        """단축키 설정"""
        # F5: 전체 새로고침
        refresh_shortcut = QShortcut(QKeySequence("F5"), self)
        refresh_shortcut.activated.connect(self.manual_refresh)
        
        # Ctrl+R: 전체 새로고침 (대안)
        refresh_shortcut2 = QShortcut(QKeySequence("Ctrl+R"), self)
        refresh_shortcut2.activated.connect(self.manual_refresh)
    
    def setup_auto_refresh(self):
        """자동 새로고침 타이머 설정"""
        self.auto_refresh_timer = QTimer(self)
        self.auto_refresh_timer.timeout.connect(self.auto_refresh)
        
        # 초기에는 비활성화
        if self.auto_refresh_enabled:
            self.auto_refresh_timer.start(self.refresh_interval)
    
    def setup_bottom_bar(self):
        """하단 정보 바 설정"""
        from PyQt6.QtWidgets import QCheckBox, QSpinBox
        
        # 하단 위젯
        bottom_widget = QWidget()
        bottom_layout = QHBoxLayout(bottom_widget)
        bottom_layout.setContentsMargins(10, 5, 10, 5)
        
        # 안내 라벨
        info_label = QLabel("💡 F5 또는 Ctrl+R: 수동 새로고침")
        info_label.setStyleSheet("color: #6b7280; font-size: 11px;")
        bottom_layout.addWidget(info_label)
        
        bottom_layout.addStretch()
        
        # 자동 새로고침 체크박스
        self.auto_refresh_checkbox = QCheckBox("🔄 자동 새로고침")
        self.auto_refresh_checkbox.setStyleSheet("font-size: 11px; font-weight: bold;")
        self.auto_refresh_checkbox.toggled.connect(self.toggle_auto_refresh)
        bottom_layout.addWidget(self.auto_refresh_checkbox)
        
        # 새로고침 간격 설정
        interval_label = QLabel("간격:")
        interval_label.setStyleSheet("font-size: 11px; margin-left: 10px;")
        bottom_layout.addWidget(interval_label)
        
        self.refresh_interval_spinbox = QSpinBox()
        self.refresh_interval_spinbox.setMinimum(10)
        self.refresh_interval_spinbox.setMaximum(300)
        self.refresh_interval_spinbox.setValue(30)
        self.refresh_interval_spinbox.setSuffix("초")
        self.refresh_interval_spinbox.setStyleSheet("font-size: 11px;")
        self.refresh_interval_spinbox.valueChanged.connect(self.update_refresh_interval)
        bottom_layout.addWidget(self.refresh_interval_spinbox)
        
        # 메인 레이아웃에 추가
        main_layout = self.centralWidget().layout()
        main_layout.addWidget(bottom_widget)
    
    def update_refresh_interval(self, seconds):
        """새로고침 간격 업데이트"""
        self.refresh_interval = seconds * 1000  # 초 → 밀리초
        
        # 타이머가 실행 중이면 재시작
        if self.auto_refresh_enabled:
            self.auto_refresh_timer.stop()
            self.auto_refresh_timer.start(self.refresh_interval)
            self.statusBar().showMessage(f"⏱️ 새로고침 간격 변경: {seconds}초", 2000)

    def manual_refresh(self):
        """수동 새로고침 (F5 또는 Ctrl+R)"""
        current_tab = self.tabs.currentIndex()
        
        # 현재 탭에 따라 새로고침
        if current_tab == 0:  # 홈 탭
            self.refresh_home_tab()
            self.statusBar().showMessage("🔄 홈 탭 새로고침 완료!", 2000)
        elif current_tab == 1:  # 검색 탭
            self.refresh_search_tab()
            self.statusBar().showMessage("🔄 검색 탭 새로고침 완료!", 2000)
        elif current_tab == 2:  # 관리 탭
            self.refresh_manage_table()
            self.statusBar().showMessage("🔄 관리 탭 새로고침 완료!", 2000)
    
    def auto_refresh(self):
        """자동 새로고침 (타이머)"""
        current_tab = self.tabs.currentIndex()
        
        # 현재 탭만 새로고침 (효율성)
        if current_tab == 0:  # 홈 탭
            self.refresh_home_tab()
        elif current_tab == 1:  # 검색 탭
            self.refresh_search_tab()
        elif current_tab == 2:  # 관리 탭
            self.refresh_manage_table()
    
    def refresh_home_tab(self):
        """홈 탭 새로고침"""
        # 상품 리스트 갱신
        self.refresh_product_list()
        
        # 현재 선택된 상품이 있으면 히스토리/그래프 갱신
        if self.current_product_id:
            self.update_history_and_graph()
        
        # 즐겨찾기 갱신
        self.refresh_bookmarks()
    
    def refresh_search_tab(self):
        """검색 탭 새로고침"""
        # 오래된 히스토리 삭제
        self.db.clear_old_search_history()
        
        # 검색 히스토리 갱신
        self.refresh_search_history()
    
    def toggle_auto_refresh(self, enabled):
        """자동 새로고침 토글"""
        self.auto_refresh_enabled = enabled
        
        if enabled:
            self.auto_refresh_timer.start(self.refresh_interval)
            self.statusBar().showMessage(f"✅ 자동 새로고침 활성화 ({self.refresh_interval // 1000}초마다)", 3000)
        else:
            self.auto_refresh_timer.stop()
            self.statusBar().showMessage("❌ 자동 새로고침 비활성화", 3000)

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

    def update_history_and_graph(self):
        """히스토리 및 그래프 갱신"""
        if not self.current_product_id:
            return
        
        # 히스토리 데이터
        history = self.db.get_price_history(self.current_product_id)
        self.history_table.setRowCount(len(history))
        
        for i, h in enumerate(history):
            history_id, product_id, crawled_date, crawled_time, price, vendor = h
            
            # 날짜
            self.history_table.setItem(i, 0, QTableWidgetItem(crawled_date))
            
            # 시간
            self.history_table.setItem(i, 1, QTableWidgetItem(crawled_time))
            
            # 매입처
            self.history_table.setItem(i, 2, QTableWidgetItem(vendor or "-"))
            
            # 가격
            price_item = QTableWidgetItem(f"{price:,}원")
            price_item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            self.history_table.setItem(i, 3, price_item)
            
            # 변동폭
            if i < len(history) - 1:
                prev_price = history[i + 1][4]
                change = price - prev_price
                if change > 0:
                    change_text = f"+{change:,}원 ▲"
                    color = QColor(220, 38, 38)
                elif change < 0:
                    change_text = f"{change:,}원 ▼"
                    color = QColor(22, 163, 74)
                else:
                    change_text = "변동없음"
                    color = QColor(107, 114, 128)
            else:
                change_text = "-"
                color = QColor(107, 114, 128)
            
            change_item = QTableWidgetItem(change_text)
            change_item.setForeground(color)
            change_item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            self.history_table.setItem(i, 4, change_item)
        
        # 그래프 업데이트 (직접 그리기!)
        sorted_history = sorted(history, key=lambda x: (x[2], x[3]))
        if sorted_history:
            dates = [f"{h[2]}\n{h[3][:5]}" for h in sorted_history]
            prices = [h[4] for h in sorted_history]
            
            self.ax.clear()
            self.ax.plot(dates, prices, marker='o', linestyle='-', color='#4f46e5', linewidth=2)
            self.ax.set_title("최근 가격 추이", fontsize=11, fontweight='bold')
            self.ax.grid(True, linestyle='--', alpha=0.4)
            self.ax.tick_params(axis='x', rotation=45, labelsize=8)
            self.figure.tight_layout()
            self.canvas.draw()
            
    def update_graph(self, history):
        """그래프 업데이트"""
        self.figure.clear()
        ax = self.figure.add_subplot(111)
        
        if not history:
            ax.text(0.5, 0.5, '히스토리 없음', 
                   ha='center', va='center', fontsize=12, color='gray')
            self.canvas.draw()
            return
        
        # 데이터 준비 (날짜순으로 정렬 - 오래된 것부터)
        dates = []
        prices = []
        
        for h in reversed(history):
            _, _, crawled_date, crawled_time, price, _ = h
            date_str = f"{crawled_date}\n{crawled_time}"
            dates.append(date_str)
            prices.append(price)
        
        # 그래프 그리기
        ax.plot(dates, prices, marker='o', linewidth=2, markersize=6, color='#3b82f6')
        ax.set_xlabel('날짜', fontsize=10)
        ax.set_ylabel('가격 (원)', fontsize=10)
        ax.set_title('가격 변동 추이', fontsize=12, fontweight='bold')
        ax.grid(True, alpha=0.3)
        
        # x축 레이블 회전
        ax.tick_params(axis='x', rotation=45, labelsize=8)
        ax.tick_params(axis='y', labelsize=9)
        
        # 레이아웃 조정
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
        """상품 수정"""
        current_row = self.manage_table.currentRow()
        if current_row < 0:
            QMessageBox.warning(self, "선택 오류", "수정할 상품을 선택하세요!")
            return
        
        product_id = int(self.manage_table.item(current_row, 0).text())
        products = self.db.get_all_products()
        product = next((p for p in products if p[0] == product_id), None)
        
        if product:
            dialog = ProductDialog(self.db, product_data=product, parent=self)
            if dialog.exec() == QDialog.DialogCode.Accepted:
                data = dialog.get_data()
                self.db.update_product(product_id, data)
                self.refresh_product_list()
                self.refresh_manage_table()
                QMessageBox.information(self, "성공", "상품이 수정되었습니다!")
    
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
                # 히스토리 추가
                products = self.db.get_all_products()
                product = next((p for p in products if p[0] == p_id), None)
                if product:
                    self.db.add_price_history(p_id, price, product[5])
                    # 현재가 업데이트
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
        
        # 화면 갱신
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

    def open_naver_shopping(self):
        """네이버 쇼핑 검색 다이얼로그 열기"""
        dialog = NaverShoppingDialog(self)
        dialog.exec()

    def open_api_settings(self):
        """API 설정 다이얼로그 열기"""
        dialog = APISettingsDialog(self.db, parent=self)
        dialog.exec()

    def execute_search(self):
        """검색 실행"""
        site = self.search_site_combo.currentText()
        keyword = self.search_keyword_input.text().strip()
        
        if not keyword:
            QMessageBox.warning(self, "입력 오류", "검색어를 입력하세요!")
            return
        
        self.search_status_label.setText(f"🔄 {site}에서 검색 중...")
        self.btn_execute_search.setEnabled(False)
        QApplication.processEvents()
        
        try:
            # 오래된 히스토리 삭제
            self.db.clear_old_search_history()
            
            results = []
            
            if site == "네이버 쇼핑":
                # API 키 확인
                client_id = self.db.get_setting('naver_api_client_id')
                client_secret = self.db.get_setting('naver_api_client_secret')
                
                if not client_id or not client_secret:
                    QMessageBox.warning(
                        self, "API 키 필요",
                        "네이버 쇼핑 검색은 API 키가 필요합니다.\n"
                        "'⚙️ 관리' 탭 → '🔑 API 설정'에서 설정하세요."
                    )
                    self.search_status_label.setText("❌ API 키 필요")
                    return
                
                api = NaverShoppingAPI(client_id, client_secret)
                results = api.search_products(keyword, max_results=20)
            
            elif site == "다나와":
                crawler = DanawaSearchCrawler()
                results = crawler.search_products(keyword, max_results=20)
            
            elif site == "쿠팡":
                # 쿠팡 API 키 확인
                access_key = self.db.get_setting('coupang_access_key')
                secret_key = self.db.get_setting('coupang_secret_key')
                
                if not access_key or not secret_key:
                    QMessageBox.warning(
                        self, "API 키 필요",
                        "쿠팡 검색은 파트너스 API 키가 필요합니다.\n"
                        "'⚙️ 관리' 탭 → '🔑 API 설정'에서 설정하세요.\n\n"
                        "쿠팡 파트너스: https://partners.coupang.com\n"
                        "(승인까지 1~3일 소요)"
                    )
                    self.search_status_label.setText("❌ API 키 필요")
                    return
                
                api = CoupangPartnersAPI(access_key, secret_key)
                results = api.search_products(keyword, max_results=20)
            
            # 결과 저장 (정렬용)
            self.current_search_results = results
            self.current_sort_column = None
            self.current_sort_order = Qt.SortOrder.AscendingOrder
            
            # 결과 테이블에 표시
            self.display_search_results(results)
            
            if results:
                min_price = min(results, key=lambda x: x[2])
                self.search_status_label.setText(f"✅ {len(results)}개 검색 완료 | 최저가: {min_price[2]:,}원")
            else:
                self.search_status_label.setText("❌ 검색 결과가 없습니다.")
        
        except Exception as e:
            QMessageBox.critical(self, "검색 실패", f"오류 발생:\n{str(e)}")
            self.search_status_label.setText(f"❌ 오류: {str(e)}")
        
        finally:
            self.btn_execute_search.setEnabled(True)
    
    def display_search_results(self, results):
        """검색 결과를 테이블에 표시"""
        self.search_result_table.setRowCount(len(results))
        
        for i, (rank, name, price, store, url) in enumerate(results):
            self.search_result_table.setItem(i, 0, QTableWidgetItem(str(rank)))
            self.search_result_table.setItem(i, 1, QTableWidgetItem(name))
            
            price_item = QTableWidgetItem(f"{price:,}원")
            price_item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            price_item.setData(Qt.ItemDataRole.UserRole, price)  # 정렬용 숫자 저장
            self.search_result_table.setItem(i, 2, price_item)
            
            url_item = QTableWidgetItem(url[:50] + "...")
            url_item.setData(Qt.ItemDataRole.UserRole, (store, name, price, url))
            self.search_result_table.setItem(i, 3, url_item)
    
    def sort_search_results(self, column):
        """헤더 클릭 시 정렬"""
        if not self.current_search_results:
            return
        
        # 정렬 순서 토글
        if self.current_sort_column == column:
            # 같은 컬럼 클릭 시 순서 반전
            if self.current_sort_order == Qt.SortOrder.AscendingOrder:
                self.current_sort_order = Qt.SortOrder.DescendingOrder
            else:
                self.current_sort_order = Qt.SortOrder.AscendingOrder
        else:
            # 다른 컬럼 클릭 시 오름차순
            self.current_sort_column = column
            self.current_sort_order = Qt.SortOrder.AscendingOrder
        
        # 정렬 실행
        reverse = (self.current_sort_order == Qt.SortOrder.DescendingOrder)
        
        if column == 0:  # 순위
            sorted_results = sorted(self.current_search_results, key=lambda x: x[0], reverse=reverse)
        elif column == 1:  # 상품명
            sorted_results = sorted(self.current_search_results, key=lambda x: x[1], reverse=reverse)
        elif column == 2:  # 가격
            sorted_results = sorted(self.current_search_results, key=lambda x: x[2], reverse=reverse)
        elif column == 3:  # URL (사실상 사이트명)
            sorted_results = sorted(self.current_search_results, key=lambda x: x[3], reverse=reverse)
        else:
            sorted_results = self.current_search_results
        
        # 테이블 업데이트
        self.display_search_results(sorted_results)
        
        # 정렬 인디케이터 표시
        header = self.search_result_table.horizontalHeader()
        header.setSortIndicator(column, self.current_sort_order)

    def add_to_history(self, item):
        """검색 결과를 히스토리에 추가"""
        row = item.row()
        url_item = self.search_result_table.item(row, 3)
        data = url_item.data(Qt.ItemDataRole.UserRole)
        
        if data:
            site, name, price, url = data
            self.db.add_search_history(site, name, price, url)
            self.refresh_search_history()
            
            # 브라우저로 열기
            import webbrowser
            webbrowser.open(url)
    
    def refresh_search_history(self):
        """히스토리 테이블 갱신"""
        history = self.db.get_search_history()
        for i in range(len(history)):
            self.history_table.insertRow(i)
        
        for i, h in enumerate(history):
            h_id, site, name, price, url, viewed_at = h
            
            # 시간 포맷
            from datetime import datetime
            dt = datetime.strptime(viewed_at, '%Y-%m-%d %H:%M:%S')
            time_str = dt.strftime('%m-%d %H:%M')
            
            self.history_table.setItem(i, 0, QTableWidgetItem(time_str))
            self.history_table.setItem(i, 1, QTableWidgetItem(site))
            self.history_table.setItem(i, 2, QTableWidgetItem(name))
            
            price_item = QTableWidgetItem(f"{price:,}원")
            price_item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            self.history_table.setItem(i, 3, price_item)
            
            url_item = QTableWidgetItem("🔗 열기")
            url_item.setData(Qt.ItemDataRole.UserRole, url)
            self.history_table.setItem(i, 4, url_item)
    
    def open_history_url(self, item):
        """히스토리에서 URL 열기"""
        row = item.row()
        url_item = self.history_table.item(row, 4)
        url = url_item.data(Qt.ItemDataRole.UserRole)
        
        if url:
            import webbrowser
            webbrowser.open(url)
    
    def clear_search_history(self):
        """검색 히스토리 전체 삭제"""
        reply = QMessageBox.question(
            self, "삭제 확인",
            "모든 검색 히스토리를 삭제하시겠습니까?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        
        if reply == QMessageBox.StandardButton.Yes:
            self.db.clear_all_search_history()
            self.refresh_search_history()
            QMessageBox.information(self, "완료", "검색 히스토리가 삭제되었습니다!")
    
    def export_history_to_excel(self):
        """검색 히스토리를 엑셀로 저장"""
        history = self.db.get_search_history()
        
        if not history:
            QMessageBox.information(self, "알림", "저장할 히스토리가 없습니다!")
            return
        
        try:
            from openpyxl import Workbook
            from openpyxl.styles import Font, Alignment, PatternFill
            from datetime import datetime
            
            # 워크북 생성
            wb = Workbook()
            ws = wb.active
            ws.title = "검색 히스토리"
            
            # 헤더
            headers = ["번호", "시간", "사이트", "상품명", "가격", "URL"]
            ws.append(headers)
            
            # 헤더 스타일
            header_fill = PatternFill(start_color="4F46E5", end_color="4F46E5", fill_type="solid")
            header_font = Font(bold=True, color="FFFFFF")
            
            for cell in ws[1]:
                cell.fill = header_fill
                cell.font = header_font
                cell.alignment = Alignment(horizontal='center', vertical='center')
            
            # 데이터
            for idx, h in enumerate(history, start=1):
                h_id, site, name, price, url, viewed_at = h
                
                dt = datetime.strptime(viewed_at, '%Y-%m-%d %H:%M:%S')
                time_str = dt.strftime('%Y-%m-%d %H:%M')
                
                ws.append([idx, time_str, site, name, price, url])
            
            # 컬럼 너비 조정
            ws.column_dimensions['A'].width = 8
            ws.column_dimensions['B'].width = 18
            ws.column_dimensions['C'].width = 12
            ws.column_dimensions['D'].width = 50
            ws.column_dimensions['E'].width = 12
            ws.column_dimensions['F'].width = 60
            
            # 저장
            from PyQt6.QtWidgets import QFileDialog
            file_path, _ = QFileDialog.getSaveFileName(
                self,
                "엑셀 파일 저장",
                f"검색히스토리_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx",
                "Excel Files (*.xlsx)"
            )
            
            if file_path:
                wb.save(file_path)
                QMessageBox.information(self, "완료", f"엑셀 파일이 저장되었습니다!\n{file_path}")
        
        except ImportError:
            QMessageBox.critical(
                self, "오류",
                "openpyxl 라이브러리가 필요합니다!\n\n"
                "설치 방법:\npip install openpyxl"
            )
        except Exception as e:
            QMessageBox.critical(self, "오류", f"엑셀 저장 실패:\n{str(e)}")
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