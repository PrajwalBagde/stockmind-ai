import os
from dotenv import load_dotenv

# Load .env FIRST before reading any os.getenv()
load_dotenv()

class Config:
    # Secret key — never None
    SECRET_KEY = os.getenv('SECRET_KEY', 'stockmind-india-jwt-2026-x9k2p7r4q8m1n5v3')

    # MySQL — read at call time via @staticmethod so env vars are always fresh
    @staticmethod
    def get_mysql_host():     return os.getenv('MYSQL_HOST', 'localhost')
    @staticmethod
    def get_mysql_user():     return os.getenv('MYSQL_USER', 'root')
    @staticmethod
    def get_mysql_password(): return os.getenv('MYSQL_PASSWORD', '')
    @staticmethod
    def get_mysql_db():       return os.getenv('MYSQL_DB', 'railway')
    @staticmethod
    def get_mysql_port():
        try:    return int(os.getenv('MYSQL_PORT', '3306'))
        except: return 3306

    # Shorthand properties for direct access
    MYSQL_HOST     = property(lambda self: os.getenv('MYSQL_HOST', 'localhost'))
    MYSQL_USER     = property(lambda self: os.getenv('MYSQL_USER', 'root'))
    MYSQL_PASSWORD = property(lambda self: os.getenv('MYSQL_PASSWORD', ''))
    MYSQL_DB       = property(lambda self: os.getenv('MYSQL_DB', 'railway'))

    @property
    def MYSQL_PORT(self):
        try:    return int(os.getenv('MYSQL_PORT', '3306'))
        except: return 3306

    # Indian Stock Symbols (NSE)
    INDIAN_STOCKS = {
        'RELIANCE.NS': 'Reliance Industries',
        'TCS.NS': 'Tata Consultancy Services',
        'INFY.NS': 'Infosys',
        'HDFCBANK.NS': 'HDFC Bank',
        'ICICIBANK.NS': 'ICICI Bank',
        'BHARTIARTL.NS': 'Bharti Airtel',
        'SBIN.NS': 'State Bank of India',
        'ITC.NS': 'ITC Limited',
        'KOTAKBANK.NS': 'Kotak Mahindra Bank',
        'LT.NS': 'Larsen & Toubro',
        'HCLTECH.NS': 'HCL Technologies',
        'AXISBANK.NS': 'Axis Bank',
        'ASIANPAINT.NS': 'Asian Paints',
        'MARUTI.NS': 'Maruti Suzuki',
        'SUNPHARMA.NS': 'Sun Pharma',
        'TITAN.NS': 'Titan Company',
        'BAJFINANCE.NS': 'Bajaj Finance',
        'WIPRO.NS': 'Wipro',
        'ULTRACEMCO.NS': 'UltraTech Cement',
        'NESTLEIND.NS': 'Nestle India',
    }

    INDICES = {
        '^NSEI': 'NIFTY 50',
        '^BSESN': 'SENSEX',
    }

    MUTUAL_FUND_CATEGORIES = [
        'Large Cap', 'Mid Cap', 'Small Cap', 'Multi Cap',
        'ELSS (Tax Saving)', 'Index Fund', 'Debt Fund',
        'Liquid Fund', 'Hybrid Fund', 'Sectoral Fund'
    ]
