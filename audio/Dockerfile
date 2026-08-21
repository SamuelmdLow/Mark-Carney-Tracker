FROM public.ecr.aws/lambda/python:3.12

RUN yum -y install wget

RUN wget -O ffmpeg.tar.xz https://github.com/BtbN/FFmpeg-Builds/releases/download/latest/ffmpeg-master-latest-linux64-gpl.tar.xz

RUN tar xvf ffmpeg.tar.xz

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