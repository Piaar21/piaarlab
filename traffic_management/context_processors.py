# # traffic_management//context_processors.py

def user_data(request):
    if request.user.is_authenticated:
        # 로그인한 사용자의 데이터를 딕셔너리로 반환합니다.
        return {'user_data': request.user}
    else:
        # 로그인하지 않은 경우 빈 딕셔너리를 반환합니다.
        return {}
