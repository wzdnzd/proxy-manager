# build: docker buildx build --platform linux/amd64 -f Dockerfile -t wzdnzd/distribute:tag --build-arg PIP_INDEX_URL="https://pypi.tuna.tsinghua.edu.cn/simple" .

FROM python:3.12.10-alpine

LABEL maintainer="wzdnzd"

# environment variables
ENV TZ=Asia/Shanghai \
    LANG=C.UTF-8 \
    LC_ALL=C.UTF-8 \
    MAX_RETRIES=3 \
    MAX_WAIT=10 \
    MAX_PROXIES_SIZE=150 \
    SUPPORTED_TARGRTS="" \
    CACHE_REFRESH_INTERVAL=14400 \
    SERVER_PORT=7860

# Expose the server port
EXPOSE ${SERVER_PORT}

# pip default index url
ARG PIP_INDEX_URL="https://pypi.org/simple"

# set work directory
WORKDIR /distribute

# copy all *.py files to /distribute
COPY *.py /distribute

# copy requirements.txt to /distribute
COPY requirements.txt /distribute

# copy subconverter to /distribute
COPY subconverter /distribute/subconverter

# delete subconverter-windows-amd.exe if exists in subconverter
RUN rm -rf /distribute/subconverter/subconverter-windows-amd.exe || true

# install dependencies
RUN pip install -i ${PIP_INDEX_URL} --no-cache-dir -r requirements.txt

# Copy entrypoint script
COPY entrypoint.sh /distribute/
RUN chmod +x /distribute/entrypoint.sh

# start and run
CMD ["python", "-u", "main.py"]