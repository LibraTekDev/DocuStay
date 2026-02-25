"""DocuStay Demo – FastAPI application."""
import logging
from pathlib import Path

# Load .env before any app code that might read config
from dotenv import load_dotenv
load_dotenv(Path(__file__).resolve().parent.parent / ".env")

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import get_settings
from app.database import Base, engine
# Import models so Base.metadata has all tables before create_all (schema source of truth)
from app.models import (  # noqa: F401
    User, OwnerProfile, Property, GuestProfile, Stay, RegionRule,
    Invitation, GuestPendingInvite, AgreementSignature, ReferenceOption,
    AuditLog, OwnerPOASignature, PendingRegistration,
    PropertyUtilityProvider, PropertyAuthorityLetter,
)
from app.routers import auth, identity, owners, guests, stays, region_rules, jle, dashboard, notifications, agreements

logger = logging.getLogger("app.startup")
settings = get_settings()
logger.info("[startup] Config loaded: app_name=%s debug=%s", settings.app_name, settings.debug)

app = FastAPI(title=settings.app_name, debug=settings.debug)
logger.info("[startup] FastAPI app created")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
logger.info("[startup] CORS middleware added")

app.include_router(auth.router)
app.include_router(identity.router)
app.include_router(owners.router)
app.include_router(guests.router)
app.include_router(stays.router)
app.include_router(region_rules.router)
app.include_router(jle.router)
app.include_router(dashboard.router)
app.include_router(notifications.router)
app.include_router(agreements.router)
logger.info("[startup] Routers registered (auth, identity, owners, guests, stays, region_rules, jle, dashboard, notifications, agreements)")


@app.on_event("startup")
def startup():
    logger.info("[startup] ---------- Startup begin ----------")
    # Mailgun
    logger.info("[startup] Step 1: Mailgun / email config")
    if settings.mailgun_api_key and settings.mailgun_domain:
        from_addr = getattr(settings, "mailgun_from_email", "") or ""
        from_domain = from_addr.split("@")[-1].lower() if "@" in from_addr else ""
        send_domain = (settings.mailgun_domain or "").strip().lower()
        if from_domain and send_domain and from_domain != send_domain:
            print(f"[Mailgun] WARNING: from={from_addr} does not match domain={settings.mailgun_domain}. Emails may not be delivered!")
            print(f"[Mailgun] Fix: in .env set MAILGUN_FROM_EMAIL=noreply@{settings.mailgun_domain} then restart")
        else:
            print(f"[Mailgun] App using domain={settings.mailgun_domain} from={from_addr or '(none)'} (verification & all emails use this)")
        logger.info("[startup] Mailgun configured: domain=%s", settings.mailgun_domain)
    else:
        print("[Mailgun] Not configured - verification emails will be skipped; set MAILGUN_API_KEY and MAILGUN_DOMAIN in .env and restart")
        logger.info("[startup] Mailgun not configured (verification emails skipped)")

    # Database
    logger.info("[startup] Step 2: Database (create tables, seed region rules)")
    try:
        Base.metadata.create_all(bind=engine)
        logger.info("[startup] Database tables created/verified")
        from app.database import SessionLocal
        from app.seed import seed_region_rules
        db = SessionLocal()
        try:
            seed_region_rules(db)
            logger.info("[startup] Region rules seeded")
        finally:
            db.close()
        logger.info("[startup] Step 2 done: database OK")
    except Exception as e:
        logger.warning("[startup] Database startup failed (tables/seed skipped). Check DATABASE_URL and network. Error: %s", e)

    # Scheduler (disabled to fix startup – cache/utility background jobs were causing startup to hang)
    # logger.info("[startup] Step 3: Background scheduler (notifications, FCC cache)")
    # try:
    #     from apscheduler.schedulers.background import BackgroundScheduler
    #     scheduler = BackgroundScheduler()
    #     if settings.notification_cron_enabled:
    #         from app.services.stay_timer import run_stay_notification_job
    #         scheduler.add_job(run_stay_notification_job, "cron", hour=9, minute=0)
    #         logger.info("[startup] Scheduler: stay notification job added (cron 09:00)")
    #     # FCC internet county cache: run monthly (1st of month at 3:00) and once at startup in background
    #     # try:
    #     #     from app.utility_providers.fcc_internet_job import run_fcc_internet_cache_job
    #     #     scheduler.add_job(run_fcc_internet_cache_job, "cron", day=1, hour=3, minute=0)
    #     #     logger.info("[startup] Scheduler: FCC internet cache job added (cron 1st of month 03:00)")
    #     #     import threading
    #     #     def run_fcc_job_once():
    #     #         try:
    #     #             logger.info("[startup] FCC internet cache job (background): starting...")
    #     #             run_fcc_internet_cache_job()
    #     #             logger.info("[startup] FCC internet cache job (background): finished")
    #     #         except Exception as e:
    #     #             logger.warning("[startup] FCC internet cache job (background) failed: %s", e)
    #     #     threading.Thread(target=run_fcc_job_once, daemon=True).start()
    #     #     logger.info("[startup] FCC internet cache job started in background thread")
    #     # except Exception as e:
    #     #     logger.debug("[startup] FCC job not scheduled: %s", e)
    #     scheduler.start()
    #     logger.info("[startup] Step 3 done: scheduler started")
    # except Exception as e:
    #     logger.warning("[startup] Scheduler failed to start: %s", e)
    logger.info("[startup] Step 3 skipped: background scheduler disabled (cache/utility jobs)")

    logger.info("[startup] ---------- Startup complete ----------")


@app.get("/")
def root():
    return {"app": settings.app_name, "status": "ok"}


@app.get("/health")
def health():
    return {"status": "healthy"}


@app.post("/db-setup")
def db_setup():
    """Dev/demo only: create tables and seed region rules if DB is now available."""
    import logging
    from fastapi.responses import JSONResponse
    log = logging.getLogger("uvicorn.error")
    try:
        Base.metadata.create_all(bind=engine)
        from app.database import SessionLocal
        from app.seed import seed_region_rules
        db = SessionLocal()
        try:
            seed_region_rules(db)
        finally:
            db.close()
        return {"status": "ok", "message": "Tables created and region rules seeded."}
    except Exception as e:
        log.exception("db-setup failed")
        return JSONResponse(
            status_code=500,
            content={"status": "error", "message": str(e)},
        )
