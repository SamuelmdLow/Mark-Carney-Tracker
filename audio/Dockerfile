FROM public.ecr.aws/lambda/python:3.12

RUN dnf install -y tar xz wget
RUN mkdir -p ffmpeg && \
    cd ffmpeg && \
    wget https://johnvansickle.com/ffmpeg/releases/ffmpeg-release-amd64-static.tar.xz && \
    tar -xvf ffmpeg-release-amd64-static.tar.xz && \
    mv ffmpeg-*-amd64-static/* . && \
    rm -rf ffmpeg-*-amd64-static && \
    rm ffmpeg-release-amd64-static.tar.xz
RUN chmod -R +x ffmpeg
ENV PATH="/ffmpeg:${PATH}"

# Copy requirements.txt
COPY lambda_container/requirements.txt ${LAMBDA_TASK_ROOT}

# Install the specified packages
RUN pip install -r requirements.txt

RUN python -c "import whisper; whisper.load_model('turbo', download_root='tmp/whisper')"

# Copy function code
COPY lambda_container/ ${LAMBDA_TASK_ROOT}

# Copy shared files
COPY shared/ ${LAMBDA_TASK_ROOT}/shared/

# Set the CMD to your handler (could also be done as a parameter override outside of the Dockerfile)
CMD [ "lambda_function.handler" ]