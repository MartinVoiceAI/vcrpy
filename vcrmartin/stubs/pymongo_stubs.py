import functools
import logging
from typing import Any, Generic, Optional

from pymongo.cursor import Cursor
from pymongo.typings import _DocumentType

from vcrmartin.constants import current_cassette
from vcrmartin.errors import CannotOverwriteExistingCassetteException
from vcrmartin.request import MongoRequest

log = logging.getLogger(__name__)


def vcr_find_one(real_find_one):
    @functools.wraps(real_find_one)
    def wrapper(self, filter: Optional[Any] = None, *args: Any, **kwargs: Any) -> Optional[_DocumentType]:
        try:
            cassette = current_cassette.get()
        except LookupError:
            return real_find_one(self, filter, *args, **kwargs)
        else:
            vcr_request = MongoRequest(*args, **kwargs)

            if cassette.can_play_response_for(vcr_request):
                log.info(f"Playing response for {vcr_request} from cassette")
                vcr_response = cassette.play_response(vcr_request)
                return vcr_response
            
            if cassette.write_protected and cassette.filter_request(vcr_request):
                raise CannotOverwriteExistingCassetteException(cassette=cassette, failed_request=vcr_request)

            log.info("%s not in cassette, sending to real server", vcr_request)

            response = real_find_one(self, filter, *args, **kwargs)
            record_responses(cassette, vcr_request, response)
            return response


def vcr_cursor_next(real_next):
    @functools.wraps(real_next)
    def wrapper(self, *args: Any, **kwargs: Any) -> _DocumentType:
        try:
            cassette = current_cassette.get()
        except LookupError:
            return real_next(self, *args, **kwargs)
        else:
            vcr_request = MongoRequest(*args, **kwargs)

            if cassette.can_play_response_for(vcr_request):
                log.info(f"Playing response for {vcr_request} from cassette")
                vcr_response = cassette.play_response(vcr_request)
                return vcr_response

            if cassette.write_protected and cassette.filter_request(vcr_request):
                raise CannotOverwriteExistingCassetteException(cassette=cassette, failed_request=vcr_request)

            log.info("%s not in cassette, sending to real server", vcr_request)

            next_data = real_next(self, *args, **kwargs)
            record_responses(cassette, vcr_request, next_data)
            return next_data