#    Licensed under the Apache License, Version 2.0 (the "License"); you may
#    not use this file except in compliance with the License. You may obtain
#    a copy of the License at
#
#         http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#    WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#    License for the specific language governing permissions and limitations
#    under the License.
from oslo_config import cfg

from ironic.common import exception
from ironic.common import rpc
from ironic.objects import base
from ironic.objects import fields


CONF = cfg.CONF


# Definition of notification levels in increasing order of severity
NOTIFY_LEVELS = {
    fields.NotificationLevel.DEBUG: 0,
    fields.NotificationLevel.INFO: 1,
    fields.NotificationLevel.WARNING: 2,
    fields.NotificationLevel.ERROR: 3,
    fields.NotificationLevel.CRITICAL: 4
}


@base.IronicObjectRegistry.register
class EventType(base.IronicObject):
    """Defines the event_type to be sent on the wire.

    An EventType must specify the object being acted on, a string describing
    the action being taken on the notification, and the phase of the action,
    if applicable.
    """
    # Version 1.0: Initial version
    VERSION = '1.0'

    fields = {
        'object': fields.StringField(nullable=False),
        'action': fields.StringField(nullable=False),
        'phase': fields.StringField(nullable=True)
    }

    def to_event_type_field(self):
        parts = ['baremetal', self.object, self.action]
        if self.obj_attr_is_set('phase') and self.phase is not None:
            parts.append(self.phase)
        return '.'.join(parts)


# NOTE(mariojv) This class will not be used directly and is just a base class
# for notifications, so we don't need to register it.
@base.IronicObjectRegistry.register_if(False)
class NotificationBase(base.IronicObject):
    """Base class for versioned notifications.

    Subclasses must define the "payload" field, which must be a subclass of
    NotificationPayloadBase.
    """
    # Version 1.0: Initial version
    VERSION = '1.0'

    fields = {
        'level': fields.NotificationLevelField(),
        'event_type': fields.ObjectField('EventType'),
        'publisher': fields.ObjectField('NotificationPublisher')
    }

    # NOTE(mariojv) This may be a candidate for something oslo.messaging
    # implements instead of in ironic.
    def _should_notify(self):
        """Determine whether the notification should be sent.

        A notification is sent when the level of the notification is
        greater than or equal to the level specified in the
        configuration, in the increasing order of DEBUG, INFO, WARNING,
        ERROR, CRITICAL.

        :return: True if notification should be sent, False otherwise.
        """
        if CONF.notification_level is None:
            return False
        return (NOTIFY_LEVELS[self.level] >=
                NOTIFY_LEVELS[CONF.notification_level])

    def emit(self, context):
        """Send the notification."""
        if not self._should_notify():
            return
        if not self.payload.populated:
            raise exception.NotificationPayloadError(
                class_name=self.__class__.__name__)
        # NOTE(mariojv) By default, oslo_versionedobjects includes a list
        # of "changed fields" for the object in the output of
        # obj_to_primitive. This is unneeded since every field of the
        # object will look changed, since each payload is a newly created
        # object, so we drop the changes.
        self.payload.obj_reset_changes()
        event_type = self.event_type.to_event_type_field()
        publisher_id = '%s.%s' % (self.publisher.service, self.publisher.host)
        payload = self.payload.obj_to_primitive()

        notifier = rpc.get_versioned_notifier(publisher_id)
        notify = getattr(notifier, self.level)
        notify(context, event_type=event_type, payload=payload)


# NOTE(mariojv) This class will not be used directly and is just a base class
# for notifications, so we don't need to register it.
@base.IronicObjectRegistry.register_if(False)
class NotificationPayloadBase(base.IronicObject):
    """Base class for the payload of versioned notifications."""

    SCHEMA = {}
    # Version 1.0: Initial version
    VERSION = '1.0'

    def __init__(self, *args, **kwargs):
        super(NotificationPayloadBase, self).__init__(*args, **kwargs)
        # If SCHEMA is empty, the payload is already populated
        self.populated = not self.SCHEMA

    def populate_schema(self, **kwargs):
        """Populate the object based on the SCHEMA and the source objects

        :param kwargs: A dict contains the source object and the keys defined
                       in the SCHEMA
        """
        for key, (obj, field) in self.SCHEMA.items():
            try:
                source = kwargs[obj]
            except KeyError:
                raise exception.NotificationSchemaObjectError(obj=obj,
                                                              source=kwargs)
            try:
                setattr(self, key, getattr(source, field))
            except Exception:
                raise exception.NotificationSchemaKeyError(obj=obj,
                                                           field=field,
                                                           key=key)
        self.populated = True


@base.IronicObjectRegistry.register
class NotificationPublisher(base.IronicObject):
    # Version 1.0: Initial version
    VERSION = '1.0'

    fields = {
        'service': fields.StringField(nullable=False),
        'host': fields.StringField(nullable=False)
    }
