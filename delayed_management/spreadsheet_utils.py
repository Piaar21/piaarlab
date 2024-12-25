# spreadsheet_utils.py
import gspread
from google.oauth2.service_account import Credentials

# 권한 범위: 읽기/쓰기를 하려면 아래처럼
SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]
# 만약 읽기만 할 경우 https://www.googleapis.com/auth/spreadsheets.readonly 등 사용 가능

def get_gspread_client(service_account_file):
    """주어진 서비스 계정 JSON 파일을 이용해 인증한 gspread.Client 객체를 반환"""
    creds = Credentials.from_service_account_file(service_account_file, scopes=SCOPES)
    client = gspread.authorize(creds)
    return client

def read_spreadsheet_data(spreadsheet_id, sheet_name, service_account_file):
    """
    스프레드시트 ID와 시트 이름을 받아 해당 범위 데이터를 읽어온다.
    spreadsheet_id: URL에서 https://docs.google.com/spreadsheets/d/SPREADSHEET_ID/edit 이 부분
    sheet_name: 시트 탭 이름 (예: "Sheet1")

    반환: 이중 리스트 형태 [ [행1], [행2], ... ]
    """
    client = get_gspread_client(service_account_file)
    sh = client.open_by_key(spreadsheet_id)
    worksheet = sh.worksheet(sheet_name)
    data = worksheet.get_all_values()
    return data

def write_spreadsheet_data(spreadsheet_id, sheet_name, service_account_file, start_cell, data):
    """
    start_cell (예: 'A1') 위치부터 data(2차원 리스트)를 기록
    """
    client = get_gspread_client(service_account_file)
    sh = client.open_by_key(spreadsheet_id)
    worksheet = sh.worksheet(sheet_name)
    worksheet.update(start_cell, data)
