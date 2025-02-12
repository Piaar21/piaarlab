import requests

proxy = "http://54.180.117.185:13128"
proxies = {
    "http": proxy,
    "https": proxy,
}

# url = "https://piaarlab.store/"  
# resp = requests.get(url)


# import requests

# # 프로토콜별(HTTP/HTTPS)로 같은 프록시를 사용한다고 가정
# proxy = "http://54.180.117.185:13128"
# proxies = {
#     "http": proxy,
#     "https": proxy,
# }

# url = "https://api.commerce.naver.com/"  # 예시용 URL
# resp = requests.get(url, proxies=proxies)
# print(resp.status_code)
# print(resp.text)