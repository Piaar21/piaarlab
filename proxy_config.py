import requests

proxy = "http://54.180.117.185:13128"
proxies = {
    "http": proxy,
    "https": proxy,
}

url = "https://piaarlab.store/"  # 여기에 요청을 보내고 싶다면
resp = requests.get(url, proxies=proxies)