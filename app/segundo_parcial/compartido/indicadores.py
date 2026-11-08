from datetime import date, datetime, timezone, timedelta
from decimal import Decimal
from fastapi import APIRouter, Depends, HTTPException, Response, Query, UploadFile, File
from sqlalchemy import select, func, cast, Date
from sqlalchemy.orm import Session
from app.api.deps import require_roles, get_current_user
from app.db.session import get_db
from app.models import User, Role, Order, Product
from app.services.saas import require_active_subscription
from app.segundo_parcial.compartido.comercio_modelos import BusinessReport
from app.segundo_parcial.compartido.reportes import facts, ReportInput
from app.segundo_parcial.cu26_exportar_reportes.cu26_excel import workbook
from app.segundo_parcial.cu28_machine_learning.cu28_forecast import forecast

admin = require_roles(Role.ADMIN)
