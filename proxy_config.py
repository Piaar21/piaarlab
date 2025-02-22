from decouple import config


# 환경 변수로부터 프록시 설정 불러오기
PROXY = config('PROXY', default='None')
proxies = {
    "http": PROXY,
    "https": PROXY,
}

