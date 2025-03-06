from django import forms  # 이 줄을 추가합니다.
from .models import Product, Traffic, UserProfile, Ad,Task

class ProductForm(forms.ModelForm):
    class Meta:
        model = Product
        fields = ['id', 'category', 'name', 'single_product_link', 'single_product_mid', 'original_link', 'original_mid', 'store_name', 'manager']
        widgets = {
            'category': forms.Select(attrs={'class': 'w-full px-2 py-1 border border-gray-300 rounded bg-white', 'disabled': True}),
            'name': forms.TextInput(attrs={'class': 'w-full px-2 py-1 border border-gray-300 rounded'}),
            'search_keyword': forms.TextInput(attrs={'class': 'w-full px-2 py-1 border border-gray-300 rounded'}),  # 추가된 부분
            'single_product_link': forms.URLInput(attrs={'class': 'w-full px-2 py-1 border border-gray-300 rounded'}),
            'single_product_mid': forms.TextInput(attrs={'class': 'w-full px-2 py-1 border border-gray-300 rounded'}),
            'original_link': forms.URLInput(attrs={'class': 'w-full px-2 py-1 border border-gray-300 rounded'}),
            'original_mid': forms.TextInput(attrs={'class': 'w-full px-2 py-1 border border-gray-300 rounded'}),
            'store_name': forms.TextInput(attrs={'class': 'w-full px-2 py-1 border border-gray-300 rounded'}),
            'manager': forms.TextInput(attrs={'class': 'w-full px-2 py-1 border border-gray-300 rounded'}),  # 추가된 부분

        }
        labels = {
            'category': '카테고리',
            'name': '상품명',
            'search_keyword': '순위 조회 키워드',  # 추가된 부분
            'single_product_link': '단일상품링크',
            'single_product_mid': '단일상품 MID값',
            'original_link': '원부 링크',
            'original_mid': '원부 MID',
            'store_name': '스토어명',
            'manager': '담당자',  # 추가된 부분

        }
        # 필드별로 required 속성 설정
        required = {
            'name': True,
            'category': True,
            'store_name': True,
            'search_keyword': False,  # 필요에 따라 True로 변경 가능
            'single_product_link': False,
            'single_product_mid': False,
            'original_link': False,
            'original_mid': False,
            'manager': False,  # 담당자는 필수 아님

        }

    def __init__(self, *args, **kwargs):
        super(ProductForm, self).__init__(*args, **kwargs)
        # 필드 비활성화 (카테고리 필드)
        self.fields['category'].disabled = True
        # 필드의 required 속성 설정
        for field_name, is_required in self.Meta.required.items():
            if field_name in self.fields:
                self.fields[field_name].required = is_required


class TrafficForm(forms.ModelForm):
    class Meta:
        model = Traffic
        fields = ['id', 'name', 'price', 'method', 'inflow_count', 'days', 'link', 'vendor']
        widgets = {
            'name': forms.TextInput(attrs={'class': 'w-full px-2 py-1 border border-gray-300 rounded'}),
            'price': forms.NumberInput(attrs={'class': 'w-full px-2 py-1 border border-gray-300 rounded'}),
            'method': forms.Select(attrs={'class': 'w-full px-2 py-1 border border-gray-300 rounded bg-white'}),
            'inflow_count': forms.NumberInput(attrs={'class': 'w-full px-2 py-1 border border-gray-300 rounded'}),
            'days': forms.NumberInput(attrs={'class': 'w-full px-2 py-1 border border-gray-300 rounded'}),
            'link': forms.URLInput(attrs={'class': 'w-full px-2 py-1 border border-gray-300 rounded'}),
            'vendor': forms.TextInput(attrs={'class': 'w-full px-2 py-1 border border-gray-300 rounded'}),  # 추가된 부분

        }
        labels = {
            'name': '트래픽명',
            'price': '금액',
            'method': '방식',
            'inflow_count': '유입수',
            'days': '일자',
            'link': '링크',
            'vendor': '업체명',  # 추가된 부분            
        }

class UserProfileForm(forms.ModelForm):
    naver_client_id = forms.CharField(
        label='NAVER_CLIENT_ID',
        required=False,
        widget=forms.TextInput(attrs={
            'class': 'shadow appearance-none border rounded w-full py-2 px-3 text-gray-700 leading-tight focus:outline-none focus:shadow-outline',
            'placeholder': 'Enter your NAVER_CLIENT_ID',
        })
    )
    naver_client_secret = forms.CharField(
        label='NAVER_CLIENT_SECRET',
        required=False,
        widget=forms.PasswordInput(attrs={
            'class': 'shadow appearance-none border rounded w-full py-2 px-3 text-gray-700 leading-tight focus:outline-none focus:shadow-outline',
            'placeholder': 'Enter your NAVER_CLIENT_SECRET',
        })
    )

    class Meta:
        model = UserProfile
        fields = ['naver_client_id', 'naver_client_secret']

class AdForm(forms.ModelForm):
    category = forms.CharField(required=False, widget=forms.TextInput(attrs={'class': 'w-full px-2 py-1 border border-gray-300 rounded'}))

    class Meta:
        model = Ad
        fields = ['id', 'start_date', 'end_date', 'channel', 'name', 'category', 'product', 'sales', 'margin', 'cost', 'memo', 'page_link', 'company']
        widgets = {
            'start_date': forms.DateInput(attrs={'type': 'date', 'class': 'w-full px-2 py-1 border border-gray-300 rounded'}),
            'end_date': forms.DateInput(attrs={'type': 'date', 'class': 'w-full px-2 py-1 border border-gray-300 rounded'}),
            'channel': forms.TextInput(attrs={'class': 'w-full px-2 py-1 border border-gray-300 rounded'}),
            'name': forms.TextInput(attrs={'class': 'w-full px-2 py-1 border border-gray-300 rounded'}),
            'product': forms.TextInput(attrs={'class': 'w-full px-2 py-1 border border-gray-300 rounded'}),
            'sales': forms.NumberInput(attrs={'class': 'w-full px-2 py-1 border border-gray-300 rounded', 'step': '1'}),
            'margin': forms.NumberInput(attrs={'class': 'w-full px-2 py-1 border border-gray-300 rounded', 'step': '1'}),
            'cost': forms.NumberInput(attrs={'class': 'w-full px-2 py-1 border border-gray-300 rounded', 'step': '1'}),
            'memo': forms.TextInput(attrs={'class': 'w-full px-2 py-1 border border-gray-300 rounded', 'maxlength': 255}),
            'page_link': forms.URLInput(attrs={'class': 'w-full px-2 py-1 border border-gray-300 rounded'}),
            'company': forms.TextInput(attrs={'class': 'w-full px-2 py-1 border border-gray-300 rounded'}),
        }


class ExcelUploadForm(forms.Form):
    file = forms.FileField(label='엑셀 파일 업로드')

class ClientForm(forms.Form):
    client_id = forms.CharField(
        label="NAVER_CLIENT_ID",
        widget=forms.TextInput(attrs={
            'class': 'shadow appearance-none border rounded w-full py-2 px-3 text-gray-700 leading-tight focus:outline-none focus:shadow-outline'
        })
    )
    client_secret = forms.CharField(
        label="NAVER_CLIENT_SECRET",
        widget=forms.TextInput(attrs={
            'class': 'shadow appearance-none border rounded w-full py-2 px-3 text-gray-700 leading-tight focus:outline-none focus:shadow-outline'
        })
    )


class TaskForm(forms.ModelForm):
    class Meta:
        model = Task
        fields = [
            'product',
            'category',
            'keyword',
            'url',
            'available_start_date',
            'available_end_date',
            'memo',
            'traffic',
            # 필요한 경우 추가 필드들
        ]
        widgets = {
            'product': forms.Select(attrs={'class': 'form-control'}),
            'category': forms.TextInput(attrs={'class': 'form-control'}),
            'keyword': forms.Select(attrs={'class': 'form-control'}),
            'url': forms.URLInput(attrs={'class': 'form-control'}),
            'available_start_date': forms.DateInput(attrs={'type': 'date', 'class': 'form-control'}),
            'available_end_date': forms.DateInput(attrs={'type': 'date', 'class': 'form-control'}),
            'memo': forms.Textarea(attrs={'class': 'form-control'}),
            'traffic': forms.Select(attrs={'class': 'form-control'}),
        }
