# build: docker buildx build --platform linux/amd64 -f Dockerfile -t wzdnzd/distribute:tag --build-arg PIP_INDEX_URL="https://pypi.tuna.tsinghua.edu.cn/simple" .

FROM python:3.12.10-alpine

### Set up user with permissions
RUN addgroup -g 1000 app && \
    adduser -u 1000 -G app -h /home/app -D app

# Switch user
USER app

# environment variables
ENV HOME=/home/app \
    TZ=Asia/Shanghai \
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
WORKDIR $HOME/distribute

# copy all *.py files to $HOME/distribute
COPY --chown=app:app *.py $HOME/distribute/

# copy requirements.txt to $HOME/distribute
COPY --chown=app:app requirements.txt $HOME/distribute/

# copy subconverter to $HOME/distribute
COPY --chown=app:app subconverter/ $HOME/distribute/subconverter/

# delete subconverter-windows-amd.exe if exists in subconverter
RUN rm -rf $HOME/distribute/subconverter/subconverter-windows-amd.exe || true

# install dependencies
RUN pip install -i ${PIP_INDEX_URL} --no-cache-dir -r requirements.txt

# start and run
CMD ["python", "-u", "main.py"]