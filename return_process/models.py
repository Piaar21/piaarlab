# return_process/models.py

from django.contrib.auth.models import AbstractBaseUser, BaseUserManager, PermissionsMixin
from django.db import models

class CustomUserManager(BaseUserManager):
    def create_user(self, email, password=None, **extra_fields):
        if not email:
            raise ValueError('이메일은 필수 입력 사항입니다.')
        email = self.normalize_email(email)
        user = self.model(email=email, **extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_superuser(self, email, password=None, **extra_fields):
        extra_fields.setdefault('is_staff', True)
        extra_fields.setdefault('is_superuser', True)
        return self.create_user(email, password, **extra_fields)

class CustomUser(AbstractBaseUser, PermissionsMixin):
    email = models.EmailField(unique=True)
    name = models.CharField(max_length=255)
    is_active = models.BooleanField(default=True)
    is_staff = models.BooleanField(default=False)

    objects = CustomUserManager()

    USERNAME_FIELD = 'email'
    REQUIRED_FIELDS = ['name']

    def __str__(self):
        return self.email

class PLATFORM_CHOICES(models.TextChoices):
    NAVER = 'naver', '네이버'
    COUPANG = 'coupang', '쿠팡'

class ReturnItem(models.Model):
    status_mapping = {
        '미처리': '미처리',
        '스캔': '스캔',
        '수거완료': '수거완료',
        '검수완료': '검수완료',
        '반품완료': '반품완료',
        '재고반영': '재고반영',
        '처리완료': '처리완료',
    }

    # 공통 필드
    # platform과 order_number는 기록 식별을 위해 필수라고 가정 (null 허용 안 함)
    platform = models.CharField(max_length=10)  # 'Naver' 또는 'Coupang'
    claim_type = models.CharField(max_length=20, null=True, blank=True, default="N/A")
    store_name = models.CharField(max_length=100, null=True, blank=True, default="N/A")
    recipient_name = models.CharField(max_length=100, null=True, blank=True, default="N/A")
    option_code = models.CharField(max_length=100, null=True, blank=True, default="")
    product_name = models.CharField(max_length=200, null=True, blank=True, default="N/A")
    option_name = models.CharField(max_length=200, null=True, blank=True, default="N/A")
    # quantity가 비어있을 수 있으므로 null/blank 허용 + 기본값 지정
    quantity = models.IntegerField(null=True, blank=True, default=1)
    invoice_number = models.CharField(max_length=50, null=True, blank=True)
    claim_status = models.CharField(max_length=50, null=True, blank=True, default="N/A")
    claim_reason = models.CharField(max_length=200, null=True, blank=True, default="N/A")
    customer_reason = models.CharField(max_length=200, null=True, blank=True, default="")
    return_shipping_charge = models.CharField(max_length=10, blank=True, null=True)
    shipping_charge_payment_method = models.CharField(max_length=100, null=True, blank=True, default="N/A")
    collect_tracking_number = models.CharField(max_length=50, null=True, blank=True)
    collect_delivery_company = models.CharField(max_length=50, null=True, blank=True)
    processing_status = models.CharField(max_length=50, null=True, blank=True, default='미처리')
    note = models.TextField(null=True, blank=True, default="")
    inspector = models.CharField(max_length=100, null=True, blank=True, default="")
    product_issue = models.CharField(max_length=50, choices=[('파손 및 불량', '파손 및 불량'), ('이상없음', '이상없음'), ('오배송', '오배송')],
                                     null=True, blank=True, default="")
    order_number = models.CharField(max_length=50)  # 식별용 필드로 필수값 유지
    delivered_date = models.DateTimeField(null=True, blank=True)
    claim_request_date = models.DateTimeField(null=True, blank=True)

    # 추가 필드
    seller_product_item_id = models.CharField(max_length=50, null=True, blank=True, default="")
    recipient_contact = models.CharField(max_length=50, null=True, blank=True, default="")
    product_order_status = models.CharField(max_length=100, blank=True, null=True)
    
    @property
    def display_status(self):
        return self.status_mapping.get(self.processing_status, self.processing_status)
    
    def __str__(self):
        return f"{self.platform} - {self.product_name}"


class NaverAccount(models.Model):
    name = models.CharField(max_length=50)  # 예: 'naver01', 'naver02'
    client_id = models.CharField(max_length=100)
    client_secret = models.CharField(max_length=100)
    access_token = models.CharField(max_length=500, null=True, blank=True)
    token_expires_at = models.DateTimeField(null=True, blank=True)

    def __str__(self):
        return self.name

class CoupangAccount(models.Model):
    name = models.CharField(max_length=50)  # 예: 'coupang01', 'coupang02'
    access_key = models.CharField(max_length=100)
    secret_key = models.CharField(max_length=100)
    vendor_id = models.CharField(max_length=100)

    def __str__(self):
        return self.name

