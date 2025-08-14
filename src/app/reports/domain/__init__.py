# reports/domain/__init__.py 
from .base import Base
from .report_model import ReportModel
# If models.py also defines table models, import them too
from .models import Report, ReportCreate, ReportUpdate # Assuming Report is a table model here 