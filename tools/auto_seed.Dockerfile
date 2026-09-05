FROM python:3.12-alpine
WORKDIR /tools
COPY auto_seed.py .
CMD ["python", "auto_seed.py"]
