# models.py

from django.db import models

class CoupangItemList(models.Model):
    # 상단 "code", "message"
    code = models.CharField(max_length=50, blank=True, null=True)
    message = models.CharField(max_length=255, blank=True, null=True)

    # data 내부 주요 필드
    sellerProductId = models.BigIntegerField(null=True, blank=True)
    sellerProductName = models.CharField(max_length=255, blank=True, null=True)
    displayCategoryCode = models.BigIntegerField(null=True, blank=True)
    categoryId = models.BigIntegerField(null=True, blank=True)
    productId = models.BigIntegerField(null=True, blank=True)
    vendorId = models.CharField(max_length=50, blank=True, null=True)
    mdId = models.CharField(max_length=50, blank=True, null=True)
    mdName = models.CharField(max_length=50, blank=True, null=True)

    saleStartedAt = models.DateTimeField(blank=True, null=True)
    saleEndedAt = models.DateTimeField(blank=True, null=True)

    displayProductName = models.CharField(max_length=255, blank=True, null=True)
    brand = models.CharField(max_length=255, blank=True, null=True)
    generalProductName = models.CharField(max_length=255, blank=True, null=True)
    productGroup = models.CharField(max_length=255, blank=True, null=True)
    statusName = models.CharField(max_length=50, blank=True, null=True)

    deliveryMethod = models.CharField(max_length=50, blank=True, null=True)
    deliveryCompanyCode = models.CharField(max_length=50, blank=True, null=True)
    deliveryChargeType = models.CharField(max_length=50, blank=True, null=True)
    deliveryCharge = models.IntegerField(default=0)
    freeShipOverAmount = models.IntegerField(default=0)
    deliveryChargeOnReturn = models.IntegerField(default=0)
    deliverySurcharge = models.IntegerField(default=0)

    # 예: "N" or "Y" 로 들어온다면 CharField로 관리
    remoteAreaDeliverable = models.CharField(max_length=1, blank=True, null=True)

    bundlePackingDelivery = models.IntegerField(default=0)
    unionDeliveryType = models.CharField(max_length=50, blank=True, null=True)

    returnCenterCode = models.CharField(max_length=50, blank=True, null=True)
    returnChargeName = models.CharField(max_length=255, blank=True, null=True)
    companyContactNumber = models.CharField(max_length=50, blank=True, null=True)
    returnZipCode = models.CharField(max_length=20, blank=True, null=True)
    returnAddress = models.CharField(max_length=255, blank=True, null=True)
    returnAddressDetail = models.CharField(max_length=255, blank=True, null=True)
    returnCharge = models.IntegerField(default=0)
    outboundShippingPlaceCode = models.BigIntegerField(null=True, blank=True)
    vendorUserId = models.CharField(max_length=100, blank=True, null=True)

    requested = models.BooleanField(default=False)

    # created_at, updated_at 등 필요 시 추가
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"[{self.sellerProductId}] {self.sellerProductName}"

class CoupangItem(models.Model):
    parent = models.ForeignKey(
        CoupangItemList, 
        on_delete=models.CASCADE,
        related_name='items'
    )

    offerCondition = models.CharField(max_length=50, blank=True, null=True)
    offerDescription = models.TextField(blank=True, null=True)
    sellerProductItemId = models.BigIntegerField(null=True, blank=True)
    vendorItemId = models.BigIntegerField(null=True, blank=True)
    itemId = models.BigIntegerField(null=True, blank=True)
    itemName = models.CharField(max_length=255, blank=True, null=True)

    originalPrice = models.IntegerField(default=0)
    salePrice = models.IntegerField(default=0)
    supplyPrice = models.IntegerField(default=0)
    maximumBuyCount = models.IntegerField(default=0)
    maximumBuyForPerson = models.IntegerField(default=0)
    outboundShippingTimeDay = models.IntegerField(default=0)
    maximumBuyForPersonPeriod = models.IntegerField(default=0)
    unitCount = models.IntegerField(default=1)

    # 예: "EVERYONE", "ADULT", 등
    adultOnly = models.CharField(max_length=50, blank=True, null=True)
    freePriceType = models.CharField(max_length=50, blank=True, null=True)
    taxType = models.CharField(max_length=50, blank=True, null=True)
    parallelImported = models.CharField(max_length=50, blank=True, null=True)
    overseasPurchased = models.CharField(max_length=50, blank=True, null=True)
    externalVendorSku = models.CharField(max_length=100, blank=True, null=True)
    pccNeeded = models.BooleanField(default=False)
    bestPriceGuaranteed3P = models.BooleanField(default=False)
    emptyBarcode = models.BooleanField(default=False)
    emptyBarcodeReason = models.CharField(max_length=255, blank=True, null=True)
    barcode = models.CharField(max_length=255, blank=True, null=True)
    saleAgentCommission = models.IntegerField(default=0)
    modelNo = models.CharField(max_length=50, blank=True, null=True)

    def __str__(self):
        return f"{self.itemName} (ItemID: {self.itemId})"
    
class CoupangItemImage(models.Model):
    parent_item = models.ForeignKey(
        CoupangItem, 
        on_delete=models.CASCADE,
        related_name='images'
    )
    imageOrder = models.IntegerField(default=0)
    imageType = models.CharField(max_length=50, blank=True, null=True)
    cdnPath = models.CharField(max_length=255, blank=True, null=True)
    vendorPath = models.CharField(max_length=255, blank=True, null=True)

    def __str__(self):
        return f"Image {self.imageOrder} of {self.parent_item}"