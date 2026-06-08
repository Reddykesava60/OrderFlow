import datetime
from django.core.management.base import BaseCommand
from django.db.models import Sum, Count
from django.utils import timezone
from core.models import Restaurant, PlatformFeeRecord, MonthlyPlatformFeeStatement
from core.timeutils import local_month_bounds

class Command(BaseCommand):
    help = 'Aggregates PlatformFeeRecord data into MonthlyPlatformFeeStatement'

    def add_arguments(self, parser):
        parser.add_argument('--all', action='store_true', help='Sync all time data')

    def handle(self, *args, **options):
        restaurants = Restaurant.objects.all()
        
        # Determine months to sync
        if options['all']:
            # Find earliest record
            first_rec = PlatformFeeRecord.objects.order_by('created_at').first()
            if not first_rec:
                self.stdout.write("No fee records found.")
                return
            start_date = first_rec.created_at.date().replace(day=1)
        else:
            # Just current month and previous month
            today = timezone.localdate()
            start_date = (today - datetime.timedelta(days=32)).replace(day=1)

        end_date = timezone.localdate().replace(day=1) + datetime.timedelta(days=32)
        
        # Iterate through months
        current_month = start_date
        while current_month <= timezone.localdate().replace(day=1):
            next_month = (current_month + datetime.timedelta(days=32)).replace(day=1)
            
            self.stdout.write(f"Syncing month: {current_month.strftime('%B %Y')}")
            month_start, month_end = local_month_bounds(current_month)
            
            for restaurant in restaurants:
                stats = PlatformFeeRecord.objects.filter(
                    restaurant=restaurant,
                    is_refunded=False,
                    created_at__gte=month_start,
                    created_at__lt=month_end,
                ).aggregate(
                    count=Count('id'),
                    revenue=Sum('order_total'),
                    fees=Sum('fee_amount')
                )
                
                if stats['count'] > 0:
                    statement, created = MonthlyPlatformFeeStatement.objects.update_or_create(
                        restaurant=restaurant,
                        month_date=current_month,
                        defaults={
                            'total_orders_count': stats['count'],
                            'total_revenue': stats['revenue'],
                            'total_fee_amount': stats['fees'],
                        }
                    )
                    action = "Created" if created else "Updated"
                    self.stdout.write(f"  - {restaurant.name}: {action} ({stats['count']} orders)")
                else:
                    # Optional: delete empty statements if they exist and aren't paid
                    MonthlyPlatformFeeStatement.objects.filter(
                        restaurant=restaurant,
                        month_date=current_month,
                        is_paid=False
                    ).delete()
            
            current_month = next_month

        self.stdout.write(self.style.SUCCESS('Successfully synced monthly statements.'))
