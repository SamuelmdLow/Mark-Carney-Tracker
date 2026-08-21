FROM public.ecr.aws/lambda/python:3.12

# Copy requirements.txt
COPY lambda_container/requirements.txt ${LAMBDA_TASK_ROOT}

RUN sudo apt-get update
RUN sudo apt-get install -y ffmpeg 

# Install the specified packages
RUN pip install -r requirements.txt

RUN python -c "import whisper; whisper.load_model('turbo', download_root='tmp/whisper')"

# Copy function code
COPY lambda_container/ ${LAMBDA_TASK_ROOT}

# Copy shared files
COPY shared/ ${LAMBDA_TASK_ROOT}/shared/

# Set the CMD to your handler (could also be done as a parameter override outside of the Dockerfile)
CMD [ "lambda_function.handler" ]