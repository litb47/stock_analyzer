from flask import Flask, render_template, request, jsonify
import requests
from bs4 import BeautifulSoup
import re
import time
import random
from concurrent.futures import ThreadPoolExecutor, as_completed
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.options import Options
from selenium.common.exceptions import TimeoutException, NoSuchElementException

app = Flask(__name__, template_folder='templates')

def get_user_agent():
    user_agents = [
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Edge/120.0.0.0 Safari/537.36',
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:121.0) Gecko/20100101 Firefox/121.0',
        'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
    ]
    return random.choice(user_agents)

def get_yahoo_recommendations(symbol):
    """מושך המלצות אנליסטים והערכות מ-Yahoo Finance"""
    try:
        chrome_options = Options()
        chrome_options.add_argument('--headless')  # ריצה ברקע
        chrome_options.add_argument('--no-sandbox')
        chrome_options.add_argument('--disable-dev-shm-usage')
        chrome_options.add_argument(f'user-agent={get_user_agent()}')
        
        driver = webdriver.Chrome(options=chrome_options)
        wait = WebDriverWait(driver, 10)
        
        recommendations = {
            'source': 'Yahoo Finance',
            'url': f'https://finance.yahoo.com/quote/{symbol}/analysis',
            'buy': 0,
            'hold': 0,
            'sell': 0
        }

        try:
            # ניסיון ראשון - דף האנליסטים
            driver.get(f'https://finance.yahoo.com/quote/{symbol}/analysis')
            print(f"מושך מידע מ-Yahoo Finance (אנליסטים)")
            
            # המתנה לטעינת הטבלה
            wait.until(EC.presence_of_element_located((By.TAG_NAME, 'table')))
            
            # חיפוש בכל הטבלאות
            tables = driver.find_elements(By.TAG_NAME, 'table')
            for table in tables:
                if 'Recommendation Rating' in table.text or 'Buy' in table.text:
                    rows = table.find_elements(By.TAG_NAME, 'tr')
                    for row in rows:
                        cols = row.find_elements(By.TAG_NAME, 'td')
                        if len(cols) >= 2:
                            text = cols[0].text.lower()
                            try:
                                count = int(cols[1].text.strip().replace(',', '') or 0)
                                if any(term in text for term in ['strong buy', 'buy']):
                                    recommendations['buy'] += count
                                elif any(term in text for term in ['hold', 'neutral']):
                                    recommendations['hold'] += count
                                elif any(term in text for term in ['sell', 'underperform']):
                                    recommendations['sell'] += count
                            except ValueError:
                                continue

            # אם לא נמצאו המלצות, ננסה בדף הסטטיסטיקות
            if recommendations['buy'] + recommendations['hold'] + recommendations['sell'] == 0:
                driver.get(f'https://finance.yahoo.com/quote/{symbol}/key-statistics')
                wait.until(EC.presence_of_element_located((By.TAG_NAME, 'table')))
                
                tables = driver.find_elements(By.TAG_NAME, 'table')
                for table in tables:
                    if 'Recommendation Rating' in table.text:
                        rows = table.find_elements(By.TAG_NAME, 'tr')
                        for row in rows:
                            if 'Recommendation Rating' in row.text:
                                try:
                                    rating = float(row.find_elements(By.TAG_NAME, 'td')[1].text)
                                    if rating <= 2:  # Strong Buy to Buy
                                        recommendations['buy'] = 5
                                    elif rating <= 3:  # Hold
                                        recommendations['hold'] = 5
                                    else:  # Sell to Strong Sell
                                        recommendations['sell'] = 5
                                    break
                                except:
                                    continue

            # אם עדיין אין המלצות, ננסה בדף הראשי
            if recommendations['buy'] + recommendations['hold'] + recommendations['sell'] == 0:
                driver.get(f'https://finance.yahoo.com/quote/{symbol}')
                wait.until(EC.presence_of_element_located((By.TAG_NAME, 'td')))
                
                elements = driver.find_elements(By.TAG_NAME, 'td')
                for element in elements:
                    if element.get_attribute('data-test') == 'RECOMMENDATION-value':
                        rating = element.text.strip().lower()
                        if 'buy' in rating or 'strong buy' in rating:
                            recommendations['buy'] = 3
                        elif 'hold' in rating or 'neutral' in rating:
                            recommendations['hold'] = 3
                        elif 'sell' in rating or 'underperform' in rating:
                            recommendations['sell'] = 3
                        break

        finally:
            driver.quit()

        total = recommendations['buy'] + recommendations['hold'] + recommendations['sell']
        print(f"Yahoo Total Recommendations: {total}")
        return recommendations if total > 0 else None

    except Exception as e:
        print(f"שגיאה במשיכת מידע מ-Yahoo: {str(e)}")
        return None

def get_marketwatch_recommendations(symbol):
    """מושך המלצות אנליסטים מ-MarketWatch"""
    try:
        headers = {
            'User-Agent': get_user_agent(),
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.5',
        }
        
        url = f'https://www.marketwatch.com/investing/stock/{symbol}/analystestimates'
        print(f"מושך מידע מ-MarketWatch: {url}")
        response = requests.get(url, headers=headers, timeout=10)
        soup = BeautifulSoup(response.text, 'html.parser')
        
        recommendations = {
            'source': 'MarketWatch',
            'url': url,
            'buy': 0,
            'hold': 0,
            'sell': 0
        }
        
        # חיפוש המלצות בטבלה
        tables = soup.find_all('table')
        for table in tables:
            rows = table.find_all('tr')
            for row in rows:
                cols = row.find_all('td')
                if len(cols) >= 2:
                    text = cols[0].text.lower()
                    try:
                        if 'buy rating' in text or 'overweight' in text:
                            count = int(cols[1].text.strip())
                            print(f"MarketWatch: Found buy - {count}")
                            recommendations['buy'] += count
                        elif 'hold rating' in text or 'neutral' in text:
                            count = int(cols[1].text.strip())
                            print(f"MarketWatch: Found hold - {count}")
                            recommendations['hold'] += count
                        elif 'sell rating' in text or 'underweight' in text:
                            count = int(cols[1].text.strip())
                            print(f"MarketWatch: Found sell - {count}")
                            recommendations['sell'] += count
                    except ValueError:
                        print(f"MarketWatch: Could not parse count from {cols[1].text}")
                        continue
        
        total = recommendations['buy'] + recommendations['hold'] + recommendations['sell']
        print(f"MarketWatch Total Recommendations: {total}")
        return recommendations if total > 0 else None

    except Exception as e:
        print(f"שגיאה במשיכת מידע מ-MarketWatch: {str(e)}")
        return None

def get_finviz_recommendations(symbol):
    """מושך המלצות אנליסטים ומידע נוסף מ-Finviz"""
    try:
        headers = {
            'User-Agent': get_user_agent(),
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.5',
            'Referer': 'https://www.google.com'
        }
        
        url = f'https://finviz.com/quote.ashx?t={symbol}'
        print(f"מושך מידע מ-Finviz: {url}")
        response = requests.get(url, headers=headers, timeout=15)
        soup = BeautifulSoup(response.text, 'html.parser')
        
        recommendations = {
            'source': 'Finviz',
            'url': url,
            'buy': 0,
            'hold': 0,
            'sell': 0,
            'institutional_ownership': None,
            'insider_ownership': None,
            'short_float': None,
            'industry_stats': {}
        }
        
        # חיפוש המלצות בטבלת הסנאפשוט
        snapshot_table = soup.find('table', {'class': 'snapshot-table2'})
        if snapshot_table:
            rows = snapshot_table.find_all('tr')
            analysts_found = False
            for row in rows:
                cols = row.find_all('td')
                for i in range(0, len(cols), 2):
                    if i + 1 < len(cols):
                        key = cols[i].text.strip()
                        value = cols[i + 1].text.strip()
                        
                        if key == 'Recom':
                            try:
                                rating = float(value)
                                print(f"Finviz: Found rating {rating}")
                                analysts_found = True
                                if rating <= 2:  # Strong Buy to Buy
                                    recommendations['buy'] = 5
                                elif rating <= 3:  # Hold
                                    recommendations['hold'] = 5
                                else:  # Sell to Strong Sell
                                    recommendations['sell'] = 5
                            except ValueError:
                                continue
                                
                        elif key == 'Analysts':
                            try:
                                total_analysts = int(value)
                                print(f"Finviz: Found {total_analysts} analysts")
                                analysts_found = True
                                if recommendations['buy'] > 0:
                                    recommendations['buy'] = total_analysts
                                elif recommendations['hold'] > 0:
                                    recommendations['hold'] = total_analysts
                                elif recommendations['sell'] > 0:
                                    recommendations['sell'] = total_analysts
                            except ValueError:
                                continue
                                
                        # מידע נוסף חשוב
                        elif key == 'Inst Own':
                            recommendations['institutional_ownership'] = value
                        elif key == 'Insider Own':
                            recommendations['insider_ownership'] = value
                        elif key == 'Short Float':
                            recommendations['short_float'] = value
                        elif key == 'Industry':
                            recommendations['industry_stats']['industry'] = value
                        elif key == 'Perf Week':
                            recommendations['industry_stats']['week_performance'] = value
                        elif key == 'Perf Month':
                            recommendations['industry_stats']['month_performance'] = value
                        elif key == 'Perf Quarter':
                            recommendations['industry_stats']['quarter_performance'] = value
                        elif key == 'Perf YTD':
                            recommendations['industry_stats']['ytd_performance'] = value
        
        total = recommendations['buy'] + recommendations['hold'] + recommendations['sell']
        print(f"Finviz Total Recommendations: {total}")
        return recommendations if total > 0 and analysts_found else None

    except Exception as e:
        print(f"שגיאה במשיכת מידע מ-Finviz: {str(e)}")
        return None

def get_investing_recommendations(symbol):
    """מושך המלצות אנליסטים מ-Investing.com"""
    try:
        chrome_options = Options()
        chrome_options.add_argument('--headless')
        chrome_options.add_argument('--no-sandbox')
        chrome_options.add_argument('--disable-dev-shm-usage')
        chrome_options.add_argument(f'user-agent={get_user_agent()}')
        
        driver = webdriver.Chrome(options=chrome_options)
        wait = WebDriverWait(driver, 10)
        
        recommendations = {
            'source': 'Investing.com',
            'url': '',
            'buy': 0,
            'hold': 0,
            'sell': 0
        }

        try:
            # ניסיון ראשון - חיפוש ישיר
            driver.get(f'https://www.investing.com/equities/{symbol.lower()}-technical')
            print(f"מושך מידע מ-Investing.com")
            
            try:
                wait.until(EC.presence_of_element_located((By.CLASS_NAME, 'technicalIndicatorsTbl')))
                recommendations['url'] = driver.current_url
            except TimeoutException:
                # ניסיון שני - חיפוש בדף החיפוש
                driver.get(f'https://www.investing.com/search/?q={symbol}')
                wait.until(EC.presence_of_element_located((By.TAG_NAME, 'a')))
                
                stock_link = None
                links = driver.find_elements(By.TAG_NAME, 'a')
                for link in links:
                    href = link.get_attribute('href') or ''
                    if '/equities/' in href and symbol.lower() in href.lower():
                        stock_link = href
                        break
                
                if stock_link:
                    driver.get(f"{stock_link}-technical")
                    wait.until(EC.presence_of_element_located((By.CLASS_NAME, 'technicalIndicatorsTbl')))
                    recommendations['url'] = driver.current_url
                else:
                    return None

            # חיפוש המלצות טכניות
            tables = driver.find_elements(By.CLASS_NAME, 'technicalIndicatorsTbl')
            for table in tables:
                rows = table.find_elements(By.TAG_NAME, 'tr')
                for row in rows:
                    cols = row.find_elements(By.TAG_NAME, 'td')
                    if len(cols) >= 2:
                        indicator = cols[0].text.strip().lower()
                        signal = cols[1].text.strip().lower()
                        
                        if 'moving averages' in indicator:
                            if 'strong buy' in signal or 'buy' in signal:
                                recommendations['buy'] += 3
                            elif 'neutral' in signal:
                                recommendations['hold'] += 3
                            elif 'sell' in signal or 'strong sell' in signal:
                                recommendations['sell'] += 3
                        
                        elif 'technical indicators' in indicator:
                            if 'strong buy' in signal or 'buy' in signal:
                                recommendations['buy'] += 2
                            elif 'neutral' in signal:
                                recommendations['hold'] += 2
                            elif 'sell' in signal or 'strong sell' in signal:
                                recommendations['sell'] += 2

            # חיפוש בסיכום הטכני
            try:
                summary = driver.find_element(By.CLASS_NAME, 'summary')
                summary_text = summary.text.lower()
                if 'buy' in summary_text or 'strong buy' in summary_text:
                    recommendations['buy'] += 1
                elif 'hold' in summary_text or 'neutral' in summary_text:
                    recommendations['hold'] += 1
                elif 'sell' in summary_text or 'strong sell' in summary_text:
                    recommendations['sell'] += 1
            except NoSuchElementException:
                pass

        finally:
            driver.quit()

        total = recommendations['buy'] + recommendations['hold'] + recommendations['sell']
        print(f"Investing.com Total Recommendations: {total}")
        return recommendations if total > 0 else None

    except Exception as e:
        print(f"שגיאה במשיכת מידע מ-Investing.com: {str(e)}")
        return None

def get_tipranks_recommendations(symbol):
    """מושך המלצות אנליסטים מ-TipRanks"""
    try:
        chrome_options = Options()
        chrome_options.add_argument('--headless')
        chrome_options.add_argument('--no-sandbox')
        chrome_options.add_argument('--disable-dev-shm-usage')
        chrome_options.add_argument(f'user-agent={get_user_agent()}')
        
        driver = webdriver.Chrome(options=chrome_options)
        wait = WebDriverWait(driver, 10)
        
        recommendations = {
            'source': 'TipRanks',
            'url': f'https://www.tipranks.com/stocks/{symbol}/forecast',
            'buy': 0,
            'hold': 0,
            'sell': 0,
            'price_target': None,
            'analyst_count': 0
        }

        try:
            driver.get(f'https://www.tipranks.com/stocks/{symbol}/forecast')
            print(f"מושך מידע מ-TipRanks")
            
            # המתנה לטעינת הדף
            wait.until(EC.presence_of_element_located((By.CLASS_NAME, 'client-components-stock-research-analysts-rating-rating')))
            
            # חיפוש המלצות אנליסטים
            rating_elements = driver.find_elements(By.CLASS_NAME, 'client-components-stock-research-analysts-rating-rating')
            for element in rating_elements:
                text = element.text.lower()
                if 'buy' in text:
                    count = int(re.search(r'\d+', text).group())
                    recommendations['buy'] = count
                elif 'hold' in text:
                    count = int(re.search(r'\d+', text).group())
                    recommendations['hold'] = count
                elif 'sell' in text:
                    count = int(re.search(r'\d+', text).group())
                    recommendations['sell'] = count
            
            # מחיר יעד
            try:
                price_target = driver.find_element(By.CLASS_NAME, 'client-components-stock-research-analysts-price-target-price-target')
                recommendations['price_target'] = price_target.text.strip('$')
            except:
                pass
            
            # מספר אנליסטים
            try:
                analyst_count = driver.find_element(By.CLASS_NAME, 'client-components-stock-research-analysts-analyst-count')
                recommendations['analyst_count'] = int(re.search(r'\d+', analyst_count.text).group())
            except:
                pass

        finally:
            driver.quit()

        total = recommendations['buy'] + recommendations['hold'] + recommendations['sell']
        print(f"TipRanks Total Recommendations: {total}")
        return recommendations if total > 0 else None

    except Exception as e:
        print(f"שגיאה במשיכת מידע מ-TipRanks: {str(e)}")
        return None

def get_globes_recommendations(symbol):
    """מושך המלצות אנליסטים מ-Globes"""
    try:
        chrome_options = Options()
        chrome_options.add_argument('--headless')
        chrome_options.add_argument('--no-sandbox')
        chrome_options.add_argument('--disable-dev-shm-usage')
        chrome_options.add_argument(f'user-agent={get_user_agent()}')
        
        driver = webdriver.Chrome(options=chrome_options)
        wait = WebDriverWait(driver, 10)
        
        recommendations = {
            'source': 'Globes',
            'url': f'https://www.globes.co.il/portal/instrument.aspx?instrumentid={symbol}',
            'buy': 0,
            'hold': 0,
            'sell': 0,
            'target_price': None
        }

        try:
            driver.get(f'https://www.globes.co.il/portal/instrument.aspx?instrumentid={symbol}')
            print(f"מושך מידע מ-Globes")
            
            # המתנה לטעינת הדף
            wait.until(EC.presence_of_element_located((By.CLASS_NAME, 'recommendations')))
            
            # חיפוש המלצות אנליסטים
            recommendations_div = driver.find_element(By.CLASS_NAME, 'recommendations')
            if recommendations_div:
                text = recommendations_div.text.lower()
                buy_match = re.search(r'קניה[:\s]+(\d+)', text)
                hold_match = re.search(r'החזק[:\s]+(\d+)', text)
                sell_match = re.search(r'מכור[:\s]+(\d+)', text)
                
                if buy_match:
                    recommendations['buy'] = int(buy_match.group(1))
                if hold_match:
                    recommendations['hold'] = int(hold_match.group(1))
                if sell_match:
                    recommendations['sell'] = int(sell_match.group(1))
                
                # מחיר יעד
                target_price = re.search(r'מחיר יעד[:\s]+₪?(\d+\.?\d*)', text)
                if target_price:
                    recommendations['target_price'] = float(target_price.group(1))

        finally:
            driver.quit()

        total = recommendations['buy'] + recommendations['hold'] + recommendations['sell']
        print(f"Globes Total Recommendations: {total}")
        return recommendations if total > 0 else None

    except Exception as e:
        print(f"שגיאה במשיכת מידע מ-Globes: {str(e)}")
        return None

def get_themarker_recommendations(symbol):
    """מושך המלצות אנליסטים מ-TheMarker"""
    try:
        chrome_options = Options()
        chrome_options.add_argument('--headless')
        chrome_options.add_argument('--no-sandbox')
        chrome_options.add_argument('--disable-dev-shm-usage')
        chrome_options.add_argument(f'user-agent={get_user_agent()}')
        
        driver = webdriver.Chrome(options=chrome_options)
        wait = WebDriverWait(driver, 10)
        
        recommendations = {
            'source': 'TheMarker',
            'url': f'https://www.themarker.com/markets/quotes/{symbol}',
            'buy': 0,
            'hold': 0,
            'sell': 0,
            'target_price': None
        }

        try:
            driver.get(f'https://www.themarker.com/markets/quotes/{symbol}')
            print(f"מושך מידע מ-TheMarker")
            
            # המתנה לטעינת הדף
            wait.until(EC.presence_of_element_located((By.CLASS_NAME, 'analysts-recommendations')))
            
            # חיפוש המלצות אנליסטים
            recommendations_div = driver.find_element(By.CLASS_NAME, 'analysts-recommendations')
            if recommendations_div:
                text = recommendations_div.text.lower()
                buy_match = re.search(r'קניה[:\s]+(\d+)', text)
                hold_match = re.search(r'החזק[:\s]+(\d+)', text)
                sell_match = re.search(r'מכור[:\s]+(\d+)', text)
                
                if buy_match:
                    recommendations['buy'] = int(buy_match.group(1))
                if hold_match:
                    recommendations['hold'] = int(hold_match.group(1))
                if sell_match:
                    recommendations['sell'] = int(sell_match.group(1))
                
                # מחיר יעד
                target_price = re.search(r'מחיר יעד[:\s]+₪?(\d+\.?\d*)', text)
                if target_price:
                    recommendations['target_price'] = float(target_price.group(1))

        finally:
            driver.quit()

        total = recommendations['buy'] + recommendations['hold'] + recommendations['sell']
        print(f"TheMarker Total Recommendations: {total}")
        return recommendations if total > 0 else None

    except Exception as e:
        print(f"שגיאה במשיכת מידע מ-TheMarker: {str(e)}")
        return None

def get_stock_info(symbol):
    """אוסף מידע על מניה מכל המקורות הזמינים"""
    try:
        print(f"\nמתחיל לאסוף מידע עבור {symbol}...")
        stock_data = {'symbol': symbol}
        
        # איסוף המלצות אנליסטים ממספר מקורות
        print("\nאוסף המלצות אנליסטים...")
        recommendations = []
        
        # מקורות חדשים
        tipranks_rec = get_tipranks_recommendations(symbol)
        if tipranks_rec:
            recommendations.append(tipranks_rec)
            
        globes_rec = get_globes_recommendations(symbol)
        if globes_rec:
            recommendations.append(globes_rec)
            
        themarker_rec = get_themarker_recommendations(symbol)
        if themarker_rec:
            recommendations.append(themarker_rec)
        
        # מקורות קיימים
        yahoo_rec = get_yahoo_recommendations(symbol)
        if yahoo_rec:
            recommendations.append(yahoo_rec)
            
        marketwatch_rec = get_marketwatch_recommendations(symbol)
        if marketwatch_rec:
            recommendations.append(marketwatch_rec)
            
        finviz_rec = get_finviz_recommendations(symbol)
        if finviz_rec:
            recommendations.append(finviz_rec)
        
        investing_rec = get_investing_recommendations(symbol)
        if investing_rec:
            recommendations.append(investing_rec)
        
        if recommendations:
            stock_data['recommendations'] = recommendations
            print(f"נאספו המלצות מ-{len(recommendations)} מקורות")
        else:
            print("לא נמצאו המלצות אנליסטים")
        
        return stock_data
        
    except Exception as e:
        print(f"שגיאה כללית באיסוף מידע: {str(e)}")
        return None

def analyze_stock_data(stock_data):
    """מנתח את המידע שנאסף"""
    if not stock_data:
        return "לא נמצא מידע על המניה"

    analysis = []
    
    # מידע בסיסי
    analysis.append(f"ניתוח עבור: {stock_data.get('name', 'לא זמין')}")
    
    # מחיר נוכחי
    price = stock_data.get('price')
    if price:
        analysis.append(f"מחיר נוכחי: ${price}")
    
    # שינוי באחוזים
    change = stock_data.get('change_percent')
    if change:
        try:
            change_float = float(change)
            if change_float > 0:
                analysis.append(f"המניה במגמת עלייה של {change_float:.2f}%")
            elif change_float < 0:
                analysis.append(f"המניה במגמת ירידה של {abs(change_float):.2f}%")
            else:
                analysis.append("המניה ללא שינוי")
        except:
            pass
    
    # מידע נוסף
    if stock_data.get('target_price'):
        analysis.append(f"\nמחיר יעד: ${stock_data['target_price']}")
    
    if stock_data.get('pe_ratio'):
        analysis.append(f"מכפיל רווח (P/E): {stock_data['pe_ratio']}")
    
    if stock_data.get('eps'):
        analysis.append(f"רווח למניה (EPS): ${stock_data['eps']}")
    
    if stock_data.get('volume'):
        analysis.append(f"נפח מסחר: {stock_data['volume']}")
    
    # ניתוח המלצות אנליסטים
    if stock_data.get('recommendations'):
        analysis.append("\nהמלצות אנליסטים וניתוח טכני ממספר מקורות:")
        print("מעבד המלצות אנליסטים...")
        
        total_buy = 0
        total_hold = 0
        total_sell = 0
        sources = []
        
        for rec in stock_data['recommendations']:
            if not rec:
                continue
                
            source = rec.get('source', 'לא ידוע')
            url = rec.get('url', '#')
            sources.append(source)
            buy = rec.get('buy', 0)
            hold = rec.get('hold', 0)
            sell = rec.get('sell', 0)
            total = buy + hold + sell
            
            if total > 0:
                print(f"מעבד המלצות מ-{source}: Buy={buy}, Hold={hold}, Sell={sell}")
                total_buy += buy
                total_hold += hold
                total_sell += sell
                
                analysis.append(f"\n{source} (מקור: {url}):")
                analysis.append(f"קנייה: {buy} אנליסטים ({buy*100/total:.1f}%)")
                analysis.append(f"החזקה: {hold} אנליסטים ({hold*100/total:.1f}%)")
                analysis.append(f"מכירה: {sell} אנליסטים ({sell*100/total:.1f}%)")
                
                # מידע נוסף מ-Yahoo Finance
                if source == 'Yahoo Finance':
                    if rec.get('price_targets'):
                        analysis.append("\nתחזיות מחיר:")
                        for target in rec['price_targets']:
                            analysis.append(f"- {target['type']}: ${target['value']}")
                    
                    if rec.get('earnings_forecast'):
                        analysis.append(f"\nתחזית רווח לרבעון הנוכחי: {rec['earnings_forecast']}")
                    
                    if rec.get('growth_estimates'):
                        analysis.append(f"תחזית צמיחה ל-5 שנים: {rec['growth_estimates']}")
                
                # מידע נוסף מ-Finviz
                elif source == 'Finviz':
                    if rec.get('institutional_ownership'):
                        analysis.append(f"\nאחזקות מוסדיות: {rec['institutional_ownership']}")
                    
                    if rec.get('insider_ownership'):
                        analysis.append(f"אחזקות אנשי פנים: {rec['insider_ownership']}")
                    
                    if rec.get('short_float'):
                        analysis.append(f"Short Float: {rec['short_float']}")
                    
                    if rec.get('industry_stats'):
                        stats = rec['industry_stats']
                        if stats.get('industry'):
                            analysis.append(f"\nענף: {stats['industry']}")
                            analysis.append("ביצועי המניה:")
                            if stats.get('week_performance'):
                                analysis.append(f"- שבוע אחרון: {stats['week_performance']}")
                            if stats.get('month_performance'):
                                analysis.append(f"- חודש אחרון: {stats['month_performance']}")
                            if stats.get('quarter_performance'):
                                analysis.append(f"- רבעון אחרון: {stats['quarter_performance']}")
                            if stats.get('ytd_performance'):
                                analysis.append(f"- מתחילת השנה: {stats['ytd_performance']}")
                
                # מידע נוסף מ-Investing.com
                elif source == 'Investing.com':
                    analysis.append("\nניתוח טכני:")
                    if rec.get('moving_averages'):
                        analysis.append(f"- ממוצעים נעים: {rec['moving_averages']}")
                    if rec.get('technical_indicators'):
                        analysis.append(f"- אינדיקטורים טכניים: {rec['technical_indicators']}")
        
        # סיכום כולל
        total = total_buy + total_hold + total_sell
        if total > 0:
            print(f"סיכום כולל: Buy={total_buy}, Hold={total_hold}, Sell={total_sell}")
            analysis.append(f"\nסיכום המלצות מ-{len(sources)} מקורות:")
            analysis.append(f"קנייה: {total_buy} אנליסטים ({total_buy*100/total:.1f}%)")
            analysis.append(f"החזקה: {total_hold} אנליסטים ({total_hold*100/total:.1f}%)")
            analysis.append(f"מכירה: {total_sell} אנליסטים ({total_sell*100/total:.1f}%)")
            
            # המלצה סופית
            if total_buy > total_hold and total_buy > total_sell:
                analysis.append("\nהמלצה כללית: קנייה 📈")
            elif total_sell > total_buy and total_sell > total_hold:
                analysis.append("\nהמלצה כללית: מכירה 📉")
            else:
                analysis.append("\nהמלצה כללית: החזקה ⚖️")
        else:
            analysis.append("\nלא נמצאו המלצות אנליסטים מספיק מפורטות")

    return "\n".join(analysis)

@app.route('/')
def home():
    return render_template('index.html')

@app.route('/analyze', methods=['POST'])
def analyze():
    """מנתח מניה לפי הסימול שהתקבל"""
    try:
        symbol = request.form.get('symbol', '').strip().upper()
        if not symbol:
            return jsonify({'success': False, 'error': 'נא להזין סימול מניה'})
        
        print(f"\n=== מתחיל ניתוח עבור {symbol} ===")
        stock_data = get_stock_info(symbol)
        
        if not stock_data:
            return jsonify({'success': False, 'error': 'לא נמצא מידע על המניה'})
            
        analysis = analyze_stock_data(stock_data)
        print("\n=== סיום ניתוח ===")
        
        return jsonify({
            'success': True,
            'stock_info': {
                'name': stock_data.get('name', symbol),
                'price': stock_data.get('price', 'N/A'),
                'change_percent': stock_data.get('change_percent', '0'),
                'target_price': stock_data.get('target_price', 'N/A'),
                'pe_ratio': stock_data.get('pe_ratio', 'N/A'),
                'eps': stock_data.get('eps', 'N/A'),
                'volume': stock_data.get('volume', 'N/A')
            },
            'analysis': analysis
        })
        
    except Exception as e:
        print(f"שגיאה בניתוח: {str(e)}")
        return jsonify({'success': False, 'error': str(e)})

if __name__ == '__main__':
    print("מפעיל את מנתח המניות החכם...")
    print("פתח את הדפדפן בכתובת: http://localhost:5000")
    app.run(debug=True) 