import unittest
import torch
from image_geometry import restore_attention_map


class AttentionAlignmentTests(unittest.TestCase):
    def test_letterbox_padding_never_appears_in_rectangular_image(self):
        for width, height, padding in [(400, 200, 'vertical'), (200, 400, 'horizontal')]:
            with self.subTest(shape=(width, height)):
                cam = torch.zeros(1, 1, 224, 224)
                if padding == 'vertical':
                    cam[:, :, :56, :] = 100
                    cam[:, :, 168:, :] = 100
                else:
                    cam[:, :, :, :56] = 100
                    cam[:, :, :, 168:] = 100
                actual = restore_attention_map(cam, width, height)
                self.assertEqual(actual.shape, (1, 1, height, width))
                self.assertEqual(actual.max().item(), 0)

    def test_hotspot_restores_to_its_original_normalized_position(self):
        cam = torch.zeros(1, 1, 224, 224)
        # Content is y=56..168. Its quarter-height, three-quarter-width point.
        cam[:, :, 83:86, 167:170] = 1
        restored = restore_attention_map(cam, 400, 200)[0, 0]
        row, col = torch.nonzero(restored == restored.max())[0].tolist()
        self.assertAlmostEqual(col / 400, .75, delta=.02)
        self.assertAlmostEqual(row / 200, .25, delta=.02)


if __name__ == '__main__':
    unittest.main()
