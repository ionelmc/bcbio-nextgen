import mock
import pytest

from bcbio.distributed import objectstore
from bcbio.distributed.objectstore import GoogleDriveServiceFactory
from bcbio.distributed.objectstore import GoogleDownloader
from bcbio.distributed.objectstore import GoogleDrive


@pytest.fixture
def mock_api(mocker):
    mocker.patch('bcbio.distributed.objectstore.ServiceAccountCredentials')
    mocker.patch('bcbio.distributed.objectstore.Http')
    mocker.patch('bcbio.distributed.objectstore.build')
    mock_http = mocker.patch('bcbio.distributed.objectstore.http')
    mocker.patch('bcbio.distributed.objectstore.open')
    media = mock_http.MediaIoBaseDownload.return_value
    media.next_chunk.side_effect = [
        (mock.Mock(), True)
    ]
    yield None


class TestGoogleDriveServiceFactory(object):
    KEY_FILE = 'TEST_API_KEY_FILE'

    def test_creates_google_credentials(self, mock_api):
        GoogleDriveServiceFactory.create(self.KEY_FILE)
        objectstore.ServiceAccountCredentials.from_json_keyfile_name\
            .assert_called_once_with(
                self.KEY_FILE,
                scopes=GoogleDriveServiceFactory.SCOPES
            )

    def test_api_scope_includes_google_drive(self):
        drive_scope = 'https://www.googleapis.com/auth/drive'
        assert drive_scope in GoogleDriveServiceFactory.SCOPES

    def test_creates_api_credentials(self, mock_api):
        cred = objectstore.ServiceAccountCredentials.from_json_keyfile_name()
        GoogleDriveServiceFactory.create('TEST')
        objectstore.build.assert_called_once_with(
            'drive', 'v3',
            cred.authorize.return_value
        )

    def test_creates_http_auth(self, mock_api):
        cred = objectstore.ServiceAccountCredentials.from_json_keyfile_name()
        GoogleDriveServiceFactory.create(self.KEY_FILE)
        cred.authorize.assert_called_once_with(objectstore.Http())

    def test_returns_service_object(self, mock_api):
        service = GoogleDriveServiceFactory.create(self.KEY_FILE)
        assert service == objectstore.build.return_value


class TestGoogleDownloader(object):
    @pytest.yield_fixture
    def media(self, mock_api):
        media = objectstore.http.MediaIoBaseDownload.return_value
        media.next_chunk.side_effect = [
            (mock.Mock(), True)
        ]
        yield media

    @pytest.yield_fixture
    def downloader(self, media):
        yield GoogleDownloader()

    def test_downloader_executes_request(self, downloader):
        fd, request = mock.Mock(), mock.Mock()
        downloader = GoogleDownloader()
        downloader.load_to_file(fd, request)
        objectstore.http.MediaIoBaseDownload.assert_called_once_with(
            fd, request, chunksize=GoogleDownloader.CHUNK_SIZE)

    def test_loads_content_in_chunks(self, downloader, media):
        fd, request = mock.Mock(), mock.Mock()
        downloader.load_to_file(fd, request)
        media.next_chunk.assert_called_once_with(
            num_retries=GoogleDownloader.NUM_RETRIES)

    def test_loads_chunks_until_done(self, downloader, media):
        fd, request = mock.Mock(), mock.Mock()
        next_chunk = [
            (mock.Mock(), False),
            (mock.Mock(), False),
            (mock.Mock(), True),

        ]
        media.next_chunk.side_effect = next_chunk
        downloader.load_to_file(fd, request)
        assert objectstore.http.MediaIoBaseDownload().next_chunk.call_count == 3


class TestGoogleDrive(object):

    @pytest.yield_fixture
    def drive(self, mock_api, mocker):
        mocker.patch('bcbio.distributed.objectstore.utils')
        yield GoogleDrive()

    @pytest.mark.parametrize(('url', 'expected'), [
        ('foo.com', False),
        ('http://example.com', False),
        ('https://example.pl', False),
        ('https://drive.google.com', False),
        ('https://drive.google.com/file/d/1234', True),
        ('https://drive.google.com/file/d/1234/view', True),
    ])
    def test_check_repource(self, drive, url, expected):
        result = drive.check_resource(url)
        assert result == expected

    @pytest.mark.parametrize('url', [
        'https://drive.google.com/file/d/TEST_ID/view',
        'https://drive.google.com/file/d/TEST_ID/',
        'https://drive.google.com/file/d/TEST_ID',
    ])
    def test_parse_remote_returns_file_id_from_url(self, drive, url):
        expected = 'TEST_ID'
        result = drive.parse_remote(url)
        assert result.file_id == expected

    def test_filename_with_json_key_is_present(self, mock_api):
        assert GoogleDrive.GOOGLE_API_KEY_FILE
        assert GoogleDrive.GOOGLE_API_KEY_FILE.endswith('.json')

    def test_download_file_can_load_file_by_id(self, drive):
        output_file = 'test_file'
        file_id = 'test_file_id'
        drive._download_file(file_id, output_file)
        drive.service.files().get_media.assert_called_once_with(fileId=file_id)

    def test_download_file_opens_output_file_for_writing(self, drive):
        drive._download_file('test_file_id', 'test_fname')
        objectstore.open.assert_called_once_with('test_fname', 'w')

    def test_download_file_calls_downlaoder(self, drive, mocker):
        mock_load = mocker.patch.object(GoogleDownloader, 'load_to_file')
        fd = objectstore.open().__enter__()
        drive._download_file('test_file_id', 'test_fname')
        mock_load.assert_called_once_with(
            fd, drive.service.files().get_media.return_value)

    def test_get_filename_calls_google_api(self, drive):
        drive._get_filename('TEST_FILE_ID')
        drive.service.files().get.assert_called_once_with(fileId='TEST_FILE_ID')

    def test_get_filename_returns_file_name_if_present(self, drive):
        drive.service.files().get().execute.return_value = {
            'name': 'TEST_FILENAME'
        }
        result = drive._get_filename('TEST_FILE_ID')
        assert result == 'TEST_FILENAME'

    def test_get_filename_returns_file_id_if_no_name(self, drive):
        drive.service.files().get().execute.return_value = {}
        result = drive._get_filename('TEST_FILE_ID')
        assert result == 'TEST_FILE_ID'

    def test_get_dl_location_from_dl_dir(self, drive):
        drive.service.files().get().execute.return_value = {
            'name': 'TEST_FILENAME'
        }
        remote_file = GoogleDrive._REMOTE_FILE('GoogleDrive', '1234ID')
        location = drive._get_dl_location(remote_file, 'input', 'path/to/dl')
        assert location == 'path/to/dl/TEST_FILENAME'

    def test_get_dl_location_from_input_dir(self, drive):
        drive.service.files().get().execute.return_value = {
            'name': 'TEST_FILENAME'
        }
        remote_file = GoogleDrive._REMOTE_FILE('GoogleDrive', '1234ID')
        location = drive._get_dl_location(remote_file, 'input', None)
        objectstore.utils.safe_makedir.assert_called_once_with(
            'input/GoogleDrive')
        assert location == 'input/GoogleDrive/TEST_FILENAME'