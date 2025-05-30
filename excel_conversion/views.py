# excel_conversion/views.py
import logging
import re
from django.shortcuts import render, redirect
from django.urls import reverse
from django.http import HttpResponse
import pandas as pd
import io
from datetime import datetime

# 로거 설정
logger = logging.getLogger(__name__)

# 매핑 테이블: 원본 코드 → 내부 코드
code_map = {
    "55415499":"p0l84ir4cx72ulg274","55415500":"p1l84ist4e72vlmfek","55415501":"4xmt1dec8ca758g75u",
    "55415502":"ND22H01-S40CDGR","55415503":"ND22H01-S40CDG","55415504":"ND22H01-S40CP",
    "55415505":"4xmt1dec8ca6e3cazq","55415506":"p7l84isonz72viyxfk","55415507":"4xmt1dec8ca200iedj",
    "55415508":"p3l84iquh972ufkbhy","55415509":"p5l84ira6j72uowva1","55415510":"p8l84irhwk72utieav",
    "55415511":"4xmt1dec8ca193sfnh","55415512":"ND22H01-S40CGR","55415513":"4y6e1d431bcd74ween",
    "55415514":"p3l84isd4s72vc3q1l","55415515":"ND22H01-S40CDBR","55415516":"ND22H01-S40CBR",
    "55415517":"ND22H01-S40CMI","55415518":"4y6e1d431bcd90b3dk","41728543":"4y6b1df1afb68a9br5",
    "41728584":"4y6b1df1afb6924i4m","41728616":"4y6b1df1afb6b31zbh","41728657":"4y6b1df1afb6ccvowl",
    "41728576":"4y6b1df1afb6ab33fp","41728601":"4ybo1d6510fc77voqr","41728637":"4y6b1df1afb6e7rnho",
    "41728660":"4ybo1d6510fc9bgfe9","41733239":"4ybo1d6510fca5fapv","41728537":"4y6b1df1afb69amczt",
    "41728564":"4y6b1df1afb676stgf","41728579":"4y8s1924d21d91hewt","41728582":"55f41dfe938763t6pj",
    "41728606":"4y6b1df1afb6d61jte","41728613":"4y6b1df1afb6ba23o8","41728641":"4y8s1924d21db5qiqw",
    "41728647":"4yc31f38be5cf0dl5k","41730890":"4y6b1df1afb6a3gthy","41730897":"4y6b1df1afb6de7u7k",
    "41733236":"4ybo1d6510fc91v3zp"
}

# Apps Script 동일 순서의 출력 헤더
out_headers = [
    "판매채널 주문일시","상품명 (필수)","옵션정보 (필수)","수량 (필수)","수취인명 (필수)",
    "전화번호1 (필수)","전화번호2","주소 (필수)","주소상세","판매채널","주문번호1","주문번호2",
    "상품코드","옵션코드","우편번호","택배사","배송방식","배송메세지","운송장번호",
    "판매금액","배송비","바코드",
    "[M] 상품코드","[M] 옵션코드","[M] 출고옵션코드",
    "관리메모1","관리메모2","관리메모3","관리메모4","관리메모5",
    "관리메모6","관리메모7","관리메모8","관리메모9","관리메모10"
]

# 키 정규화 함수: '(필수)' 제거, '[M]'→'M', 공백 제거
def normalize_key(key: str) -> str:
    key = re.sub(r"\s*\(.*?\)", "", key)
    key = key.replace("[M]", "M")
    return key.replace(" ", "").strip()


def excel_upload(request):
    """
    Excel 업로드 시 Apps Script 매핑 로직을 적용해 세션에 누적 저장
    """
    data_list = request.session.get('excel_data', [])
    error_message = None
    success_message = None

    if request.method == 'POST':
        files = request.FILES.getlist('excel_files')
        if not files:
            error_message = '파일이 선택되지 않았습니다.'
            logger.warning('No files selected for upload.')
        else:
            total_new = 0
            for f in files:
                if not f.name.lower().endswith(('.xls', '.xlsx')):
                    error_message = '엑셀 파일(.xlsx, .xls)만 업로드 가능합니다.'
                    logger.warning('Invalid file type: %s', f.name)
                    continue
                try:
                    # 전체 시트 raw 읽기
                    df = pd.read_excel(f, header=None)

                    # 1) 상단 고정 필드 추출
                    order_no      = str(df.iat[9, 2])  # C10
                    order_manager = str(df.iat[9, 7])  # H10
                    addr1         = str(df.iat[12, 3]) # D13
                    addr2         = str(df.iat[12, 4]) # E13
                    address       = addr1
                    detail_addr   = addr2
                    phone1        = str(df.iat[12, 8]) # I13
                    phone2        = ''
                    sales_channel = '로켓배송'

                    # 2) '합계' 앞 데이터 구간 찾기
                    total_idx = None
                    for idx, row in df.iterrows():
                        if row.astype(str).str.strip().eq('합계').any():
                            total_idx = idx
                            break
                    last_idx = (total_idx - 1) if total_idx is not None else (df.shape[0] - 1)

                    # 3) 헤더 병합 (20~21행)
                    r20 = df.iloc[19].fillna('').astype(str).tolist()
                    r21 = df.iloc[20].fillna('').astype(str).tolist()
                    hdrs = [((a+' '+b).strip() if a and b else a or b) for a, b in zip(r20, r21)]

                    # 정규화된 헤더 인덱스 맵
                    norm_hdr_idx = {normalize_key(h): i for i, h in enumerate(hdrs)}

                    # 4) 짝수행(22행부터) 데이터 매핑
                    for row_idx in range(21, last_idx + 1, 2):
                        row = df.iloc[row_idx]
                        def get_val(raw_key):
                            idx = norm_hdr_idx.get(normalize_key(raw_key))
                            return row.iat[idx] if idx is not None else ''

                        # 필드 추출
                        raw = str(get_val('상품명/옵션/BARCODE') or '')
                        parts = [p.strip() for p in raw.split(',', 1)]
                        product_name = parts[0]
                        option_info  = parts[1] if len(parts) > 1 else ''
                        orig_code    = str(get_val('상품코드') or '')
                        mapped_code  = code_map.get(orig_code, orig_code)
                        qty          = get_val('발주수량')
                        amount       = df.iat[row_idx, 12]

                        # 5) 값 구성
                        values = []
                        for hdr in out_headers:
                            nk = normalize_key(hdr)
                            if nk == normalize_key('상품명 (필수)'):      val = product_name
                            elif nk == normalize_key('옵션정보 (필수)'):    val = option_info
                            elif nk == normalize_key('수량 (필수)'):        val = qty
                            elif nk == normalize_key('수취인명 (필수)'):    val = f"{get_val('물류센터')} (로켓배송)"
                            elif nk == normalize_key('전화번호1 (필수)'):   val = phone1
                            elif nk == normalize_key('전화번호2'):          val = phone2
                            elif nk == normalize_key('주소 (필수)'):        val = address
                            # elif nk == normalize_key('주소상세'):          val = detail_addr
                            elif nk == normalize_key('판매채널'):           val = sales_channel
                            elif nk == normalize_key('주문번호1'):          val = order_no
                            elif nk == normalize_key('주문번호2'):          val = ''
                            elif nk == normalize_key('판매금액'):           val = amount
                            elif nk in [normalize_key(x) for x in ['[M] 상품코드','[M] 옵션코드','[M] 출고옵션코드']]: val = mapped_code
                            elif nk == normalize_key('관리메모1'):         val = order_manager
                            else:                                           val = ''
                            values.append(val)

                        # 6) 키를 정규화된 상태로 저장
                        mapped_row = { normalize_key(hdr): val for hdr, val in zip(out_headers, values) }
                        data_list.append(mapped_row)
                        total_new += 1

                    logger.info('Mapped %d rows from file %s', total_new, f.name)
                except Exception as e:
                    error_message = f'파일 매핑 중 오류: {e}'
                    logger.error('Error mapping %s: %s', f.name, e)

            # 세션에 저장 및 피드백
            request.session['excel_data'] = data_list
            success_message = f"{len(files)}개 파일 처리, 총 {total_new}건 매핑되었습니다."
            logger.info(success_message)

    return render(request, 'excel_conversion/excel_upload.html', {
        'data_list': data_list,
        'error_message': error_message,
        'success_message': success_message,
    })


def excel_download(request):
    data_list = request.session.get('excel_data', [])
    if not data_list:
        return redirect(reverse('excel_conversion:excel_upload'))
    # DataFrame 생성 및 컬럼 순서, 이름 지정
    df = pd.DataFrame(data_list)
    norm_keys = [normalize_key(h) for h in out_headers]
    df = df[norm_keys]
    df.columns = out_headers

    output = io.BytesIO()
    # engine을 openpyxl로 사용 (requirements.txt에 openpyxl 필요)
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        df.to_excel(writer, index=False, sheet_name='주문데이터')
    output.seek(0)

    filename = f'주문데이터_{datetime.now().date().isoformat()}.xlsx'
    resp = HttpResponse(
        output.read(),
        content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
    )
    resp['Content-Disposition'] = f'attachment; filename="{filename}"'
    return resp

def excel_clear(request):
    if request.method == 'POST':
        request.session.pop('excel_data', None)
        logger.info('Session data cleared.')
    return redirect(reverse('excel_conversion:excel_upload'))