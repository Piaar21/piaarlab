# resources.py엑셀업로드

from import_export import resources, fields
from import_export.widgets import CharWidget
from .models import Product

class ProductResource(resources.ModelResource):
    category = fields.Field(column_name='카테고리', attribute='category', widget=CharWidget())
    name = fields.Field(column_name='상품명', attribute='name', widget=CharWidget())
    single_product_link = fields.Field(column_name='단일상품링크', attribute='single_product_link', widget=CharWidget())
    single_product_mid = fields.Field(column_name='단일상품 MID값', attribute='single_product_mid', widget=CharWidget())
    original_link = fields.Field(column_name='원부 링크', attribute='original_link', widget=CharWidget())
    original_mid = fields.Field(column_name='원부 MID', attribute='original_mid', widget=CharWidget())
    store_name = fields.Field(column_name='스토어명', attribute='store_name', widget=CharWidget())

    class Meta:
        model = Product
        fields = ('category', 'name', 'single_product_link', 'single_product_mid', 'original_link', 'original_mid', 'store_name')
