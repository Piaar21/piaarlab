from django.db import models

class ProductOptionMapping(models.Model):
    option_code = models.CharField(max_length=100, unique=True)
    product_name = models.CharField(max_length=255)
    option_name = models.CharField(max_length=255)
    store_name = models.CharField(max_length=255)

    def __str__(self):
        return f"{self.option_code} - {self.product_name}/{self.option_name}"

class DelayedOrder(models.Model):
    option_code = models.CharField(max_length=100)
    customer_name = models.CharField(max_length=100)
    customer_contact = models.CharField(max_length=100)
    order_product_name = models.CharField(max_length=255, blank=True)
    order_option_name = models.CharField(max_length=255, blank=True)
    seller_product_name = models.CharField(max_length=255, blank=True)
    seller_option_name = models.CharField(max_length=255, blank=True)
    order_number_1 = models.CharField(max_length=255, blank=True)
    order_number_2 = models.CharField(max_length=255, blank=True)
    store_name = models.CharField(max_length=255, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    def __str__(self):
        return f"{self.option_code} - {self.customer_name}"

class OptionStoreMapping(models.Model):
    option_code = models.CharField(max_length=100, unique=True)
    store_name = models.CharField(max_length=255)

    def __str__(self):
        return f"{self.option_code} -> {self.store_name}"