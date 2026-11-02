from django.db import models


class Customer(models.Model):
    name = models.CharField(max_length=80)
    email = models.EmailField()
    city = models.CharField(max_length=60)

    def __str__(self):
        return self.name


class Order(models.Model):
    STATUS = [("new", "New"), ("paid", "Paid"), ("packed", "Packed"), ("shipped", "Shipped"), ("returned", "Returned")]
    number = models.CharField(max_length=12, unique=True)
    customer = models.ForeignKey(Customer, on_delete=models.PROTECT)
    status = models.CharField(max_length=10, choices=STATUS)
    total = models.DecimalField(max_digits=8, decimal_places=2)
    tracking = models.CharField(max_length=30, blank=True)
    notes = models.TextField(blank=True)

    def __str__(self):
        return self.number
