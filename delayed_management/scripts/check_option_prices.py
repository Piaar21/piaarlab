def run():
    print("Run script start!")

    from delayed_management.models import OptionMapping
    target_code = "4xxu1d576e7fbaqhbn"

    om = OptionMapping.objects.filter(option_code=target_code).first()
    if not om:
        print(f"[ERROR] code='{target_code}' not found.")
        return

    print(f"> OptionMapping(option_code={om.option_code})")
    print(f"  - base_sale_price={om.base_sale_price}, discounted_price={om.discounted_price}")

    details = om.platform_details.all()
    if not details:
        print("  - No platform_details found.")
    else:
        for idx, det in enumerate(details, start=1):
            print(
                f"  [{idx}] detail_id={det.id}, platform={det.platform_name}, "
                f"option_price={det.price}, stock={det.stock}, ..."
            )
