# rankings/models.py

from django.db import models
from django.utils import timezone
from django.contrib.auth.models import User
from django.dispatch import receiver
from encrypted_model_fields.fields import EncryptedCharField
from django.db.models.signals import post_save
from django.db.utils import OperationalError, ProgrammingError
from django.conf import settings

class Product(models.Model):
    CATEGORY_CHOICES = [
        ('네이버', '네이버'),
        ('쿠팡', '쿠팡'),
        ('오늘의집', '오늘의집'),
    ]

    name = models.CharField(max_length=255,verbose_name='상품명')  # 상품명
    category = models.CharField(max_length=10, choices=CATEGORY_CHOICES,null=True, blank=True, verbose_name='카테고리')
    search_keyword = models.CharField(max_length=255, null=True, blank=True, verbose_name='순위 조회 키워드')  # 추가된 부분
    single_product_link = models.URLField(blank=True, null=True,verbose_name='단일상품링크')  # 단일상품링크
    single_product_mid = models.CharField(max_length=100, blank=True, null=True,verbose_name='단일상품 MID값')  # 단일상품 MID값
    original_link = models.URLField(default='',verbose_name='원부 링크',blank=True, null=True)  # 빈 문자열을 기본값으로 설정
    original_mid = models.CharField(max_length=100,default='', verbose_name='원부 MID',blank=True, null=True)  # 원부 MID (필수)
    store_name = models.CharField(max_length=255,default='',verbose_name='스토어명')  # 스토어명 (필수)
    manager = models.CharField(max_length=100, default='', blank=True, null=True, verbose_name='담당자')  # 담당자 필드 추가

    # yesterday_rank = models.IntegerField(null=True, blank=True)


    def __str__(self):
        return self.name

class Keyword(models.Model):
    name = models.CharField(max_length=255)

    def __str__(self):
        return self.name


    
class Traffic(models.Model):
    METHOD_CHOICES = [
        ('유입플', '유입플'),
        ('리워드', '리워드'),
        ('복합플', '복합플'),
        # 필요한 방식들을 추가하세요
    ]

    name = models.CharField(max_length=255, verbose_name='트래픽명')
    price = models.DecimalField(max_digits=10, decimal_places=0, verbose_name='금액')
    method = models.CharField(max_length=50, choices=METHOD_CHOICES, verbose_name='방식')
    inflow_count = models.PositiveIntegerField(verbose_name='유입수')
    link = models.URLField(max_length=200, blank=True, null=True)  # 링크 필드 추가
    days = models.IntegerField()  # 일수 필드 추가
    created_at = models.DateTimeField(auto_now_add=True, verbose_name='등록일자')
    updated_at = models.DateTimeField(auto_now=True, verbose_name='수정일자')
    vendor = models.CharField(max_length=255, blank=True, null=True, verbose_name='업체명')  # 추가된 필드    


    def __str__(self):
        return self.name

class Task(models.Model):
    product = models.ForeignKey(Product, null=True, blank=True, on_delete=models.SET_NULL)
    category = models.CharField(max_length=100)
    keyword = models.ForeignKey(Keyword, on_delete=models.CASCADE)
    url = models.URLField(max_length=200)
    start_rank = models.IntegerField(null=True, blank=True)
    yesterday_rank = models.IntegerField(null=True, blank=True)
    current_rank = models.IntegerField(null=True, blank=True)
    difference_rank = models.IntegerField(null=True, blank=True)
    status = models.CharField(max_length=20, default='효과없음')  # 상태 필드 추가
    last_checked_date = models.DateTimeField(auto_now=True)
    available_start_date = models.DateField()
    available_end_date = models.DateField()
    memo = models.TextField(null=True, blank=True)
    ticket_count = models.IntegerField(default=0)
    product_name = models.CharField(max_length=100, null=True, blank=True)
    original_link = models.URLField(max_length=200, null=True, blank=True)
    original_mid = models.CharField(max_length=100, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    traffic = models.ForeignKey('Traffic', on_delete=models.SET_NULL, null=True, blank=True)
    original_end_date = models.DateField(null=True, blank=True)
    is_completed = models.BooleanField(default=False)
    ending_rank = models.IntegerField(null=True, blank=True)
    is_extended = models.BooleanField(default=False)  # 연장된 작업인지 표시
    original_task = models.ForeignKey('self', null=True, blank=True, on_delete=models.SET_NULL, related_name='extended_tasks')  # 원본 작업 참조
    needs_attention = models.BooleanField(default=False)  # 추가된 부분

    def save(self, *args, **kwargs):
        # difference_rank 계산
        if self.yesterday_rank is not None and self.current_rank is not None:
            self.difference_rank = self.yesterday_rank - self.current_rank
        super().save(*args, **kwargs)

class Ranking(models.Model):
    task = models.ForeignKey(
        'Task',
        on_delete=models.CASCADE,
        related_name='rankings',
    )
    product = models.ForeignKey(Product, on_delete=models.CASCADE)
    keyword = models.ForeignKey(Keyword, on_delete=models.CASCADE)
    rank = models.IntegerField(null=True, blank=True)  # null과 blank 허용
    date_time = models.DateTimeField(auto_now_add=True)
    memo = models.TextField(blank=True, null=True)  # 메모
    traffic_name = models.CharField(max_length=255, blank=True, null=True)  # 트래픽 명
    traffic_count = models.IntegerField(default=0)  # 이용권 수
    traffic_period = models.DateField(blank=True, null=True)  # 이용가능일자

    def __str__(self):
        return f"{self.product.name} - {self.keyword.name} - {self.rank}"
    

class UserProfile(models.Model):
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    naver_client_id = models.CharField(max_length=100, blank=True, null=True)
    naver_client_secret = models.CharField(max_length=100, blank=True, null=True)

    def __str__(self):
        return self.user.username

@receiver(post_save, sender=User)
def create_user_profile(sender, instance, created, **kwargs):
    if kwargs.get('raw', False):
        return  # 데이터 로딩 시 시그널 무시
    if created:
        try:
            UserProfile.objects.create(user=instance)
        except (OperationalError, ProgrammingError):
            pass



class Ad(models.Model):
    start_date = models.DateField()
    end_date = models.DateField()
    channel = models.CharField(max_length=100)
    name = models.CharField(max_length=200)
    category = models.CharField(max_length=100)
    product = models.CharField(max_length=255)
    sales = models.DecimalField(max_digits=15, decimal_places=2)
    margin = models.DecimalField(max_digits=15, decimal_places=2)
    cost = models.DecimalField(max_digits=15, decimal_places=2)
    memo = models.CharField(max_length=255, blank=True)
    page_link = models.URLField(blank=True, null=True)
    company = models.CharField(max_length=100)

    @property
    def profit(self):
        return self.margin - self.cost

    @property
    def margin_rate(self):
        if self.sales:
            return (self.margin / self.sales) * 100
        return 0

    @property
    def profit_rate(self):
        if self.sales:
            return ((self.margin - self.cost) / self.sales) * 100
        return 0

    @property
    def roas(self):
        if self.cost:
            return (self.sales / self.cost) * 100
        return 0

    @property
    def roi(self):
        if self.cost:
            return ((self.margin - self.cost) / self.cost) * 100
        return 0
    def __str__(self):
        return self.name
from django import forms  # 이 줄을 추가합니다.
from .models import Product, Traffic, UserProfile, Ad

# class ProductForm(forms.ModelForm):
#     original_link = forms.URLField(required=False, widget=forms.URLInput(attrs={'class': 'form-control'}))
#     original_mid = forms.CharField(required=False, widget=forms.TextInput(attrs={'class': 'form-control'}))

#     class Meta:
#         model = Product
#         fields = ['category', 'name', 'single_product_link', 'single_product_mid', 'original_link', 'original_mid', 'store_name']
#         widgets = {
#             'category': forms.Select(attrs={'class': 'form-control'}),
#             'name': forms.TextInput(attrs={'class': 'form-control'}),
#             'single_product_link': forms.URLInput(attrs={'class': 'form-control'}),
#             'single_product_mid': forms.TextInput(attrs={'class': 'form-control'}),
#             'store_name': forms.TextInput(attrs={'class': 'form-control'}),
#         }
#         labels = {
#             'name': '상품명',
#             'category': '카테고리',
#             'single_product_link': '단일상품링크',
#             'single_product_mid': '단일상품 MID값',
#             'original_link': '원부 링크',
#             'original_mid': '원부 MID',
#             'store_name': '스토어명',
#             # 기타 필드들에 대한 레이블 지정...
#         }

#     def __init__(self, *args, **kwargs):
#         super(ProductForm, self).__init__(*args, **kwargs)
#         self.fields['category'].disabled = True  # 카테고리 필드 비활성화


class TrafficForm(forms.ModelForm):
    class Meta:
        model = Traffic
        fields = ['name', 'price', 'method', 'inflow_count','days']
        widgets = {
            'date': forms.DateInput(attrs={'type': 'date'}),
        }

class UserProfileForm(forms.ModelForm):
    naver_client_id = forms.CharField(label='NAVER_CLIENT_ID', required=False)
    naver_client_secret = forms.CharField(label='NAVER_CLIENT_SECRET', required=False, widget=forms.PasswordInput)

    class Meta:
        model = UserProfile
        fields = ['naver_client_id', 'naver_client_secret']

class AdForm(forms.ModelForm):
    category = models.CharField(max_length=100, blank=True, null=True)
    class Meta:
        

        model = Ad
        fields = '__all__'
        widgets = {
            'memo': forms.TextInput(attrs={'maxlength': 255}),
            'start_date': forms.DateInput(attrs={'type': 'date'}),
            'end_date': forms.DateInput(attrs={'type': 'date'}),
        }


class ExcelUploadForm(forms.Form):
    file = forms.FileField(label='엑셀 파일 업로드')