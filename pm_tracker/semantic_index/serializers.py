from rest_framework import serializers
from generic_relations.relations import GenericRelatedField

from attachments.models import Attachment
from schedule_items.models import ScheduleItem
from semantic_index.models import SemanticIndex


class SemanticIndexSerializer(serializers.HyperlinkedModelSerializer):
    
    content_object = GenericRelatedField({
        Attachment: serializers.HyperlinkedRelatedField(
            queryset = Attachment.objects.all(),
            view_name='attachment-detail',
        ),
        ScheduleItem: serializers.HyperlinkedRelatedField(
            queryset = ScheduleItem.objects.all(),
            view_name='scheduleitem-detail',
        ),
    })

    class Meta:
        model = SemanticIndex
        fields = ["id", "body", "datetime", "label", "content_type_id", "object_id", "content_object"]

